ALTER TABLE erp.sales ADD COLUMN payment jsonb;

CREATE OR REPLACE FUNCTION erp.erp_stock_command(p_device uuid,p_operation uuid,p_kind text,p_payload jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE actor erp.employee_profiles; prior erp.processed_operations; fingerprint text; result jsonb;
    med uuid; target uuid; qty bigint; available bigint; reserved bigint; allocation erp.stock_allocations;
    item jsonb; sale_id uuid; subtotal numeric(12,2):=0; tax numeric(12,2); unit numeric(12,2);
    payment jsonb; paid numeric; tendered numeric; change_due numeric;
    sale_record jsonb; movement jsonb; items jsonb:='[]'::jsonb; movements jsonb:='[]'::jsonb;
BEGIN
    actor := erp.sync_actor(p_device);
    IF p_operation IS NULL OR p_kind IS NULL OR p_kind NOT IN ('receive','allocate','sale') OR p_payload IS NULL
       OR jsonb_typeof(p_payload)<>'object' OR octet_length(p_payload::text)>262144 THEN RAISE EXCEPTION 'Invalid stock operation'; END IF;
    IF p_kind IN ('receive','allocate') AND actor.role<>'superadmin' THEN RAISE EXCEPTION 'Superadmin access required' USING ERRCODE='42501'; END IF;
    INSERT INTO erp.sync_heads(pharmacy_id) VALUES(actor.pharmacy_id) ON CONFLICT DO NOTHING;
    PERFORM 1 FROM erp.sync_heads WHERE pharmacy_id=actor.pharmacy_id FOR UPDATE;
    fingerprint := encode(sha256(convert_to(jsonb_build_array(p_kind,p_payload)::text,'UTF8')),'hex');
    SELECT * INTO prior FROM erp.processed_operations WHERE pharmacy_id=actor.pharmacy_id AND device_id=p_device AND operation_id=p_operation;
    IF prior.operation_id IS NOT NULL THEN
      IF prior.payload_hash<>fingerprint OR prior.actor_id<>actor.id THEN RAISE EXCEPTION 'Operation ID reused'; END IF;
      RETURN prior.result;
    END IF;
    IF p_kind IN ('receive','allocate') THEN
      med := (p_payload->>'medicine_id')::uuid; qty := (p_payload->>'quantity')::bigint;
      IF qty IS NULL OR qty<=0 OR qty>2147483647 OR NOT EXISTS(SELECT 1 FROM erp.medicines WHERE pharmacy_id=actor.pharmacy_id AND id=med AND deleted_at IS NULL)
        THEN RAISE EXCEPTION 'Invalid medicine or quantity'; END IF;
      IF p_kind='receive' THEN
        INSERT INTO erp.stock_movements AS m(pharmacy_id,medicine_id,device_id,movement_type,quantity_change,occurred_at,note)
          VALUES(actor.pharmacy_id,med,p_device,'received',qty,now(),p_payload->>'note') RETURNING to_jsonb(m) INTO movement;
        PERFORM erp.log_change(actor.pharmacy_id,'stock_movements',(movement->>'id')::uuid,1,p_operation,movement);
        result := jsonb_build_object('status','applied','movement',movement);
      ELSE
        target := (p_payload->>'device_id')::uuid;
        IF NOT EXISTS(SELECT 1 FROM erp.registered_devices WHERE pharmacy_id=actor.pharmacy_id AND id=target AND revoked_at IS NULL) THEN RAISE EXCEPTION 'Device not authorized'; END IF;
        SELECT coalesce(sum(quantity_change),0) INTO available FROM erp.stock_movements WHERE pharmacy_id=actor.pharmacy_id AND medicine_id=med;
        -- Include revoked devices: their offline reservations cannot be reassigned safely.
        SELECT coalesce(sum(quantity_granted-quantity_consumed),0) INTO reserved FROM erp.stock_allocations WHERE pharmacy_id=actor.pharmacy_id AND medicine_id=med;
        IF qty>available-reserved THEN RAISE EXCEPTION 'Insufficient unallocated stock' USING ERRCODE='P0001'; END IF;
        INSERT INTO erp.stock_allocations(pharmacy_id,device_id,medicine_id,quantity_granted)
          VALUES(actor.pharmacy_id,target,med,qty)
          ON CONFLICT(pharmacy_id,device_id,medicine_id) DO UPDATE
          SET quantity_granted=erp.stock_allocations.quantity_granted+qty,version=erp.stock_allocations.version+1,updated_at=now()
          RETURNING * INTO allocation;
        result := jsonb_build_object('status','applied','allocation',to_jsonb(allocation));
      END IF;
    ELSE
      sale_id := (p_payload->>'id')::uuid; tax := (p_payload->>'tax_amount')::numeric;
      IF sale_id IS NULL OR tax IS NULL OR tax<0 OR jsonb_typeof(p_payload->'items') IS DISTINCT FROM 'array'
        OR jsonb_array_length(p_payload->'items') NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'Invalid sale'; END IF;
      IF (SELECT count(*) FROM jsonb_array_elements(p_payload->'items')) <> (SELECT count(DISTINCT x->>'medicine_id') FROM jsonb_array_elements(p_payload->'items') x) THEN RAISE EXCEPTION 'Duplicate medicine'; END IF;
      FOR item IN SELECT * FROM jsonb_array_elements(p_payload->'items') LOOP
        med := (item->>'medicine_id')::uuid; qty := (item->>'quantity')::bigint; unit := (item->>'unit_price')::numeric;
        IF qty IS NULL OR qty<=0 OR qty>2147483647 OR unit IS NULL OR unit<0 THEN RAISE EXCEPTION 'Invalid sale item'; END IF;
        IF NOT EXISTS(SELECT 1 FROM erp.medicines WHERE pharmacy_id=actor.pharmacy_id AND id=med AND deleted_at IS NULL) THEN RAISE EXCEPTION 'Medicine unavailable'; END IF;
        UPDATE erp.stock_allocations SET quantity_consumed=quantity_consumed+qty,version=version+1,updated_at=now()
          WHERE pharmacy_id=actor.pharmacy_id AND device_id=p_device AND medicine_id=med AND quantity_granted-quantity_consumed>=qty;
        IF NOT FOUND THEN RAISE EXCEPTION 'Sale exceeds device allocation' USING ERRCODE='P0001'; END IF;
        subtotal := subtotal+qty*unit;
      END LOOP;
      payment := p_payload->'payment';
      IF payment IS NOT NULL AND payment <> 'null'::jsonb THEN
        IF jsonb_typeof(payment) <> 'object' OR COALESCE(payment->>'method','') NOT IN ('cash','upi','card','bank_transfer')
          THEN RAISE EXCEPTION 'Invalid payment method'; END IF;
        paid := (payment->>'amount')::numeric;
        tendered := (payment->>'tendered')::numeric;
        change_due := (payment->>'change')::numeric;
        IF paid IS NULL OR tendered IS NULL OR change_due IS NULL
           OR paid <> subtotal+tax OR tendered < paid OR change_due <> tendered-paid
           OR paid < 0 OR tendered > 9999999999.99
           OR paid <> round(paid,2) OR tendered <> round(tendered,2) OR change_due <> round(change_due,2)
          THEN RAISE EXCEPTION 'Payment does not match bill'; END IF;
        IF payment->>'method' <> 'cash' AND (tendered <> paid OR COALESCE(length(btrim(payment->>'reference')),0) = 0)
          THEN RAISE EXCEPTION 'Digital payment requires exact amount and reference'; END IF;
        IF length(payment->>'reference') > 100 THEN RAISE EXCEPTION 'Payment reference too long'; END IF;
      END IF;
      IF p_payload->>'prescription_id' IS NOT NULL THEN
        UPDATE erp.prescriptions SET status='dispensed',version=version+1,updated_at=now()
          WHERE pharmacy_id=actor.pharmacy_id AND id=(p_payload->>'prescription_id')::uuid AND status='pending' AND deleted_at IS NULL
          RETURNING to_jsonb(erp.prescriptions) INTO result;
        IF NOT FOUND THEN RAISE EXCEPTION 'Prescription unavailable'; END IF;
        PERFORM erp.log_change(actor.pharmacy_id,'prescriptions',(result->>'id')::uuid,(result->>'version')::bigint,p_operation,result);
      END IF;
      INSERT INTO erp.sales AS s(pharmacy_id,id,device_id,customer_id,prescription_id,status,subtotal,tax_amount,total_amount,occurred_at,payment)
        VALUES(actor.pharmacy_id,sale_id,p_device,(p_payload->>'customer_id')::uuid,(p_payload->>'prescription_id')::uuid,'completed',subtotal,tax,subtotal+tax,(p_payload->>'occurred_at')::timestamptz,payment)
        RETURNING to_jsonb(s) INTO sale_record;
      FOR item IN SELECT * FROM jsonb_array_elements(p_payload->'items') LOOP
        med := (item->>'medicine_id')::uuid; qty := (item->>'quantity')::bigint; unit := (item->>'unit_price')::numeric;
        INSERT INTO erp.sale_items AS i(pharmacy_id,sale_id,medicine_id,quantity,unit_price,line_total)
          VALUES(actor.pharmacy_id,sale_id,med,qty,unit,qty*unit) RETURNING to_jsonb(i) INTO result;
        items := items||jsonb_build_array(result);
        INSERT INTO erp.stock_movements AS m(pharmacy_id,medicine_id,device_id,sale_id,movement_type,quantity_change,occurred_at)
          VALUES(actor.pharmacy_id,med,p_device,sale_id,'sale',-qty,(p_payload->>'occurred_at')::timestamptz) RETURNING to_jsonb(m) INTO movement;
        movements := movements||jsonb_build_array(movement);
      END LOOP;
      -- One change contains the sale and dependent rows so pull can apply atomically.
      result := sale_record||jsonb_build_object('items',items,'stock_movements',movements);
      PERFORM erp.log_change(actor.pharmacy_id,'sales',sale_id,1,p_operation,result);
      result := jsonb_build_object('status','applied','sale',result);
    END IF;
    INSERT INTO erp.processed_operations(pharmacy_id,device_id,operation_id,actor_id,payload_hash,result)
      VALUES(actor.pharmacy_id,p_device,p_operation,actor.id,fingerprint,result);
    RETURN result;
END $$;
REVOKE ALL ON FUNCTION erp.erp_stock_command(uuid,uuid,text,jsonb) FROM PUBLIC,anon,authenticated;
NOTIFY pgrst,'reload schema';
