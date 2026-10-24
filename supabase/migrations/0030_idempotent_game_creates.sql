-- 생성 재시도는 같은 요청의 영수증만 재생한다. 원문 payload/메모는 중복 저장하지 않는다.
-- 영수증은 tombstone과 함께 보존하며 계정 삭제 시 FK cascade로 제거한다.
create table public.game_create_receipts (
    user_id uuid not null references auth.users(id) on delete cascade,
    request_id uuid not null,
    payload_hash bytea not null check (octet_length(payload_hash) = 32),
    result jsonb not null,
    created_at timestamptz not null default now(),
    primary key (user_id, request_id)
);
alter table public.game_create_receipts enable row level security;
revoke all on table public.game_create_receipts from public, anon, authenticated;

-- 기존 검증/CAS 계약을 재사용하되 각 항목을 새 호출로 분리하여 CAS 변수 누수를 막는다.
alter function public.apply_game_changes(integer, integer, jsonb)
    rename to apply_game_changes_legacy;
revoke all on function public.apply_game_changes_legacy(integer, integer, jsonb)
    from public, anon, authenticated, service_role;

create function public.apply_game_changes(
    sync_schema_version integer, payload_version integer, changes jsonb
)
returns jsonb
language plpgsql security definer set search_path = ''
as $$
declare
    uid uuid := auth.uid();
    item jsonb;
    request_key uuid;
    fingerprint bytea;
    receipt public.game_create_receipts%rowtype;
    result jsonb;
    results jsonb := '[]'::jsonb;
begin
    if uid is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;
    if sync_schema_version is distinct from 1 then
        raise exception 'unsupported sync_schema_version' using errcode = '22023';
    end if;
    if payload_version is distinct from 2 then
        raise exception 'unsupported payload_version' using errcode = '22023';
    end if;
    if changes is null or jsonb_typeof(changes) <> 'array' then
        raise exception 'changes must be a JSON array' using errcode = '22023';
    end if;
    if jsonb_array_length(changes) not between 1 and 200 then
        raise exception 'batch size must be between 1 and 200' using errcode = '22023';
    end if;

    -- cursor가 이미 사용자별 쓰기를 직렬화한다. 먼저 같은 순서로 잠가 배치 간 교착을 피한다.
    perform pg_advisory_xact_lock(hashtextextended('game_changes:' || uid::text, 0));

    for item in select * from jsonb_array_elements(changes) loop
        if jsonb_typeof(item) <> 'object' then
            raise exception 'change item must be an object' using errcode = '22023';
        end if;
        if not (item ? 'request_id') then
            result := public.apply_game_changes_legacy(1, 2, jsonb_build_array(item));
            results := results || (result -> 'results');
            continue;
        end if;
        if item ->> 'op' is distinct from 'create' then
            raise exception 'request_id is only supported for create' using errcode = '22023';
        end if;
        begin
            request_key := (item ->> 'request_id')::uuid;
        exception when invalid_text_representation then
            raise exception 'invalid request_id' using errcode = '22023';
        end;
        if request_key is null then
            raise exception 'request_id is required' using errcode = '22023';
        end if;
        -- 진단용 client_version만 제외한다. ID, 필드 생략/null, 시각을 포함한 요청 의미는 고정한다.
        fingerprint := extensions.digest((item - 'request_id' - 'client_version')::text, 'sha256');
        select * into receipt from public.game_create_receipts
        where user_id = uid and request_id = request_key;
        if found then
            if receipt.payload_hash <> fingerprint then
                raise exception 'request_id reused with different payload' using errcode = '22023';
            end if;
            -- 이후 수정/삭제/모드 비활성화와 무관하게 최초 성공만 확인한다. 행을 덮어쓰지 않는다.
            results := results || jsonb_build_array(receipt.result || '{"replayed":true}'::jsonb);
            continue;
        end if;
        result := public.apply_game_changes_legacy(1, 2, jsonb_build_array(item - 'request_id'))
            -> 'results' -> 0;
        if result ->> 'status' = 'applied' then
            insert into public.game_create_receipts(user_id, request_id, payload_hash, result)
            values (uid, request_key, fingerprint, result);
        end if;
        results := results || jsonb_build_array(result);
    end loop;
    return jsonb_build_object('results', results);
end;
$$;
revoke all on function public.apply_game_changes(integer, integer, jsonb) from public, anon;
grant execute on function public.apply_game_changes(integer, integer, jsonb) to authenticated;
notify pgrst, 'reload schema';
