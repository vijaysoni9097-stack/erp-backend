-- Purchase orders and shared preferences join the same authenticated, durable log.
CREATE TABLE erp.purchase_orders (
    pharmacy_id uuid NOT NULL REFERENCES erp.pharmacies(id), id uuid NOT NULL,
    request_id uuid NOT NULL, request_hash text NOT NULL CHECK(request_hash ~ '^[a-f0-9]{64}$'),
    created_by uuid NOT NULL, supplier_id uuid NOT NULL, supplier_name varchar(150) NOT NULL,
    currency varchar(3) NOT NULL CHECK(currency ~ '^[A-Z]{3}$'),
    status text NOT NULL CHECK(status IN ('pending_approval','approved','in_transit','delivered','cancelled')),
    expected_delivery date, notes text CHECK(length(notes)<=1000),
    total_amount numeric(12,2) NOT NULL CHECK(total_amount>=0),
    items jsonb NOT NULL CHECK(jsonb_typeof(items)='array' AND jsonb_array_length(items) BETWEEN 1 AND 100),
    version bigint NOT NULL DEFAULT 1 CHECK(version>0),
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz,
    PRIMARY KEY(pharmacy_id,id), UNIQUE(pharmacy_id,request_id),
    FOREIGN KEY(pharmacy_id,created_by) REFERENCES erp.employee_profiles(pharmacy_id,id),
    FOREIGN KEY(pharmacy_id,supplier_id) REFERENCES erp.suppliers(pharmacy_id,id)
);
ALTER TABLE erp.purchase_orders ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON erp.purchase_orders FROM PUBLIC,anon,authenticated;

-- Existing clients and existing entities retain their original semantics.
ALTER FUNCTION erp.erp_sync_push(uuid,uuid,text,uuid,bigint,jsonb,boolean) RENAME TO erp_sync_push_core;
REVOKE ALL ON FUNCTION erp.erp_sync_push_core(uuid,uuid,text,uuid,bigint,jsonb,boolean) FROM PUBLIC,anon,authenticated;

CREATE FUNCTION erp.erp_sync_push(p_device uuid,p_operation uuid,p_entity text,p_record uuid,p_base_version bigint,p_payload jsonb,p_deleted boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE actor erp.employee_profiles; prior erp.processed_operations; fingerprint text;
    old jsonb; saved jsonb; result jsonb; next_version bigint; payload jsonb;
    allowed text[]; key text; item jsonb; lines jsonb:='[]'::jsonb;
    qty numeric; price numeric; total numeric:=0; med uuid;
BEGIN
    IF p_entity NOT IN ('purchase_orders','pharmacy_settings','notification_preferences') THEN
        RETURN erp.erp_sync_push_core(p_device,p_operation,p_entity,p_record,p_base_version,p_payload,p_deleted);
    END IF;
    actor:=erp.sync_actor(p_device);
    IF p_operation IS NULL OR p_record IS NULL OR p_base_version IS NULL OR p_base_version<0 OR p_deleted IS DISTINCT FROM false
       OR p_payload IS NULL OR jsonb_typeof(p_payload)<>'object' OR octet_length(p_payload::text)>262144 THEN
        RAISE EXCEPTION 'Invalid business sync operation';
    END IF;
    IF p_entity='purchase_orders' AND actor.role NOT IN ('superadmin','admin','pharmacist') THEN
        RAISE EXCEPTION 'Purchasing access required' USING ERRCODE='42501';
    END IF;
    allowed:=CASE p_entity
      WHEN 'purchase_orders' THEN ARRAY['request_id','request_hash','supplier_id','supplier_name','currency','status','expected_delivery','notes','total_amount','created_at','items']
      WHEN 'pharmacy_settings' THEN ARRAY['default_prescription_duration_days','auto_refill_reminders','refill_reminder_lead_days','allow_generic_substitution','default_pharmacy_notes','low_stock_threshold','low_stock_alerts_enabled','expiry_alert_lead_days','expiry_alerts_enabled','auto_reorder_enabled','default_supplier_id']
      WHEN 'notification_preferences' THEN ARRAY['event_type','email_enabled','sms_enabled','in_app_enabled'] END;
    FOR key IN SELECT jsonb_object_keys(p_payload) LOOP
        IF NOT(key=ANY(allowed)) THEN RAISE EXCEPTION 'Unsupported business field'; END IF;
    END LOOP;
    IF p_entity='pharmacy_settings' AND p_record IS DISTINCT FROM md5(actor.pharmacy_id::text||':pharmacy_settings')::uuid THEN
        RAISE EXCEPTION 'Invalid shared settings identity';
    END IF;
    IF p_entity='notification_preferences' AND p_record IS DISTINCT FROM md5(actor.pharmacy_id::text||':notification_preferences:'||(p_payload->>'event_type'))::uuid THEN
        RAISE EXCEPTION 'Invalid notification settings identity';
    END IF;
    fingerprint:=encode(sha256(convert_to(jsonb_build_array(p_entity,p_record,p_base_version,p_payload,p_deleted)::text,'UTF8')),'hex');
    INSERT INTO erp.sync_heads(pharmacy_id) VALUES(actor.pharmacy_id) ON CONFLICT DO NOTHING;
    PERFORM 1 FROM erp.sync_heads WHERE pharmacy_id=actor.pharmacy_id FOR UPDATE;
    SELECT * INTO prior FROM erp.processed_operations WHERE pharmacy_id=actor.pharmacy_id AND device_id=p_device AND operation_id=p_operation;
    IF prior.operation_id IS NOT NULL THEN
        IF prior.payload_hash<>fingerprint OR prior.actor_id<>actor.id THEN RAISE EXCEPTION 'Operation ID reused with different contents'; END IF;
        RETURN prior.result;
    END IF;
    IF p_entity='purchase_orders' THEN
        SELECT to_jsonb(t) INTO old FROM erp.purchase_orders t WHERE pharmacy_id=actor.pharmacy_id AND id=p_record;
    ELSIF p_entity='pharmacy_settings' THEN
        SELECT to_jsonb(t)||jsonb_build_object('id',p_record) INTO old FROM erp.pharmacy_settings t WHERE pharmacy_id=actor.pharmacy_id;
    ELSE
        SELECT to_jsonb(t)||jsonb_build_object('id',p_record) INTO old FROM erp.notification_preferences t WHERE pharmacy_id=actor.pharmacy_id AND event_type=p_payload->>'event_type';
    END IF;
    IF coalesce((old->>'version')::bigint,0)<>p_base_version OR old->>'deleted_at' IS NOT NULL OR (p_entity='purchase_orders' AND old IS NOT NULL) THEN
        result:=jsonb_build_object('status','conflict','current',old);
        INSERT INTO erp.sync_conflicts(pharmacy_id,device_id,operation_id,entity,record_id,reason,proposed,current_record)
          VALUES(actor.pharmacy_id,p_device,p_operation,p_entity,p_record,'version_conflict',p_payload,old);
    ELSE
        next_version:=p_base_version+1;
        payload:=coalesce(old,'{}'::jsonb)||p_payload||jsonb_build_object('pharmacy_id',actor.pharmacy_id,'id',p_record,'version',next_version,'updated_at',now());
        IF p_entity='purchase_orders' THEN
            IF p_payload->>'status' IS DISTINCT FROM 'pending_approval' OR jsonb_typeof(p_payload->'items') IS DISTINCT FROM 'array'
               OR jsonb_array_length(p_payload->'items') NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'Invalid purchase order'; END IF;
            IF NOT EXISTS(SELECT 1 FROM erp.suppliers WHERE pharmacy_id=actor.pharmacy_id AND id=(p_payload->>'supplier_id')::uuid AND deleted_at IS NULL) THEN RAISE EXCEPTION 'Supplier unavailable'; END IF;
            IF (SELECT count(DISTINCT x->>'medicine_id') FROM jsonb_array_elements(p_payload->'items') x)<>jsonb_array_length(p_payload->'items') THEN RAISE EXCEPTION 'Duplicate purchase medicine'; END IF;
            FOR item IN SELECT value FROM jsonb_array_elements(p_payload->'items') LOOP
                IF item->>'quantity' IS NULL OR item->>'quantity' !~ '^[1-9][0-9]{0,9}$' OR item->>'unit_price' IS NULL OR item->>'unit_price' !~ '^[0-9]{1,10}([.][0-9]{1,2})?$' THEN RAISE EXCEPTION 'Invalid purchase quantity or cost'; END IF;
                qty:=(item->>'quantity')::numeric; price:=(item->>'unit_price')::numeric; med:=(item->>'medicine_id')::uuid;
                IF qty>2147483647 OR NOT EXISTS(SELECT 1 FROM erp.medicines WHERE pharmacy_id=actor.pharmacy_id AND id=med AND deleted_at IS NULL) THEN RAISE EXCEPTION 'Medicine unavailable'; END IF;
                IF coalesce(length(item->>'medicine_name'),0) NOT BETWEEN 1 AND 150 OR coalesce(length(item->>'sku'),0) NOT BETWEEN 1 AND 50 OR coalesce(length(item->>'batch_number'),0) NOT BETWEEN 1 AND 80 THEN RAISE EXCEPTION 'Invalid purchase item details'; END IF;
                total:=total+qty*price;
                lines:=lines||jsonb_build_array(jsonb_build_object('medicine_id',med,'medicine_name',item->>'medicine_name','sku',item->>'sku','batch_number',item->>'batch_number','quantity',qty::bigint,'unit_price',price,'line_total',qty*price));
            END LOOP;
            IF total>9999999999.99 THEN RAISE EXCEPTION 'Purchase total too large'; END IF;
            payload:=payload||jsonb_build_object('created_by',actor.id,'total_amount',total,'items',lines,'created_at',coalesce(p_payload->>'created_at',now()::text));
            INSERT INTO erp.purchase_orders AS t SELECT r.* FROM jsonb_populate_record(NULL::erp.purchase_orders,payload) r RETURNING to_jsonb(t) INTO saved;
        ELSIF p_entity='pharmacy_settings' THEN
            INSERT INTO erp.pharmacy_settings AS t SELECT r.* FROM jsonb_populate_record(NULL::erp.pharmacy_settings,payload) r
            ON CONFLICT(pharmacy_id) DO UPDATE SET
              default_prescription_duration_days=excluded.default_prescription_duration_days,auto_refill_reminders=excluded.auto_refill_reminders,
              refill_reminder_lead_days=excluded.refill_reminder_lead_days,allow_generic_substitution=excluded.allow_generic_substitution,
              default_pharmacy_notes=excluded.default_pharmacy_notes,low_stock_threshold=excluded.low_stock_threshold,
              low_stock_alerts_enabled=excluded.low_stock_alerts_enabled,expiry_alert_lead_days=excluded.expiry_alert_lead_days,
              expiry_alerts_enabled=excluded.expiry_alerts_enabled,auto_reorder_enabled=excluded.auto_reorder_enabled,
              default_supplier_id=excluded.default_supplier_id,version=excluded.version,updated_at=excluded.updated_at
            RETURNING to_jsonb(t)||jsonb_build_object('id',p_record) INTO saved;
        ELSE
            INSERT INTO erp.notification_preferences AS t SELECT r.* FROM jsonb_populate_record(NULL::erp.notification_preferences,payload) r
            ON CONFLICT(pharmacy_id,event_type) DO UPDATE SET email_enabled=excluded.email_enabled,sms_enabled=excluded.sms_enabled,
              in_app_enabled=excluded.in_app_enabled,version=excluded.version,updated_at=excluded.updated_at
            RETURNING to_jsonb(t)||jsonb_build_object('id',p_record) INTO saved;
        END IF;
        PERFORM erp.log_change(actor.pharmacy_id,p_entity,p_record,next_version,p_operation,saved);
        result:=jsonb_build_object('status','applied','record',saved);
    END IF;
    INSERT INTO erp.processed_operations(pharmacy_id,device_id,operation_id,actor_id,payload_hash,result)
      VALUES(actor.pharmacy_id,p_device,p_operation,actor.id,fingerprint,result);
    RETURN result;
END $$;
REVOKE ALL ON FUNCTION erp.erp_sync_push(uuid,uuid,text,uuid,bigint,jsonb,boolean) FROM PUBLIC,anon,authenticated;
NOTIFY pgrst,'reload schema';
