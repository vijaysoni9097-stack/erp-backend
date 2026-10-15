-- Reuse the existing authorization, version, stock and idempotency checks.
CREATE FUNCTION public.erp_sync_push_batch(p_device uuid,p_device_secret text,p_operations jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE operation jsonb; result jsonb; receipts jsonb := '[]'::jsonb;
BEGIN
    PERFORM erp.verify_device(p_device,p_device_secret);
    IF p_operations IS NULL OR jsonb_typeof(p_operations) <> 'array' THEN
        RAISE EXCEPTION 'Operations must be an array';
    END IF;
    IF jsonb_array_length(p_operations) NOT BETWEEN 1 AND 200
       OR octet_length(p_operations::text) > 2097152 THEN
        RAISE EXCEPTION 'Batch exceeds allowed size';
    END IF;
    FOR operation IN SELECT value FROM jsonb_array_elements(p_operations) LOOP
        IF operation->>'p_kind' = 'sale' THEN
            result := erp.erp_stock_command(p_device,(operation->>'p_operation')::uuid,
                'sale',operation->'p_payload');
        ELSE
            result := erp.erp_sync_push(p_device,(operation->>'p_operation')::uuid,
                operation->>'p_entity',(operation->>'p_record')::uuid,
                (operation->>'p_base_version')::bigint,operation->'p_payload',
                COALESCE((operation->>'p_deleted')::boolean,false));
        END IF;
        receipts := receipts || jsonb_build_array(jsonb_build_object(
            'operation_id',operation->>'p_operation','result',result));
        EXIT WHEN result->>'status' = 'conflict';
    END LOOP;
    RETURN jsonb_build_object('receipts',receipts);
END $$;
REVOKE ALL ON FUNCTION public.erp_sync_push_batch(uuid,text,jsonb) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.erp_sync_push_batch(uuid,text,jsonb) TO authenticated;
NOTIFY pgrst,'reload schema';
