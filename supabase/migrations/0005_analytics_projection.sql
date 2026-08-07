-- 0005_analytics_projection.sql
-- 분석용 듀얼 데이터 경계(로드맵 6.2, 7.4).
--
-- - analytics 스키마는 클라이언트(anon/authenticated)가 접근할 수 없다.
-- - 등록 계정 games는 DB 트리거가 허용된 필드만 observation으로 projection한다.
-- - 게스트는 Guest Ingest Edge Function이 service_role로 호출하는 제한된
--   ingest 함수만 사용한다. 직접 식별자와 note는 스키마에 존재하지 않는다.
-- - 등록/게스트 경로 모두 같은 game UUID(sync_id) 기반 observation key를
--   사용해 이후 import에서도 분석 행이 중복되지 않는다(로드맵 6.4).

create schema analytics;

revoke all on schema analytics from public;
revoke usage on schema analytics from anon, authenticated;

-- 운영 user_id ↔ 분석 contributor_key 재결합을 막기 위한 서버 전용 salt.
-- service secret이 아니며 서버 밖으로 내보내지 않는다(로드맵 6.3).
create table analytics.contributor_salt (
    id boolean primary key default true check (id),
    salt text not null
);

insert into analytics.contributor_salt (salt)
values (encode(extensions.gen_random_bytes(32), 'hex'));

create or replace function analytics.pseudonym_for(subject text)
returns text
language sql
security definer
set search_path = ''
as $$
    select encode(
        extensions.digest(
            convert_to(
                (select salt from analytics.contributor_salt) || subject,
                'utf8'
            ),
            'sha256'
        ),
        'hex'
    );
$$;

revoke all on function analytics.pseudonym_for(text) from public;

-- 분석용 duel observation(로드맵 7.4). 이메일, 표시 이름, note, 토큰,
-- 파일 경로, OS 사용자명, 직접 auth user ID 컬럼은 존재하지 않는다.
create table analytics.duel_observations (
    observation_id uuid primary key default gen_random_uuid(),
    -- 중복 방지용 제한된 참조: 클라이언트가 생성한 game UUID(sync_id).
    source_game_id uuid not null unique,
    -- 목적 제한된 기여자 pseudonym(등록: user_id 기반, 게스트: installation 기반).
    contributor_key text,
    played_at_local text not null
        check (played_at_local ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$'),
    timezone_offset_minutes integer
        check (timezone_offset_minutes is null
               or timezone_offset_minutes between -1440 and 1440),
    server_received_at timestamptz not null default now(),
    result text not null check (result in ('win', 'lose')),
    turn_order text not null check (turn_order in ('first', 'second')),
    my_deck text,
    opp_deck text,
    turns integer check (turns is null or turns >= 0),
    end_reason text,
    play_context_id text,
    standing_kind text
        check (standing_kind is null
               or standing_kind in ('rank', 'rating', 'event_points')),
    rank_tier_before text,
    rank_tier_after text,
    rank_division_before integer,
    rank_division_after integer,
    rating_before integer,
    rating_after integer,
    event_points_before integer,
    event_points_after integer,
    event_id text,
    event_stage_id text,
    environment_version_id text,
    deck_catalog_version_id text,
    client_version text,
    payload_version integer not null check (payload_version >= 1),
    source_kind text not null
        check (source_kind in ('registered', 'guest', 'import')),
    quality_flags text[] not null default '{}',
    -- 개인 기록 삭제는 관측 철회로 취급하고 물리 삭제하지 않는다(로드맵 9.3).
    withdrawn_at timestamptz,
    withdrawal_source text
        check (withdrawal_source is null
               or withdrawal_source in ('registered', 'guest'))
);

create table analytics.ingestion_batches (
    batch_id uuid primary key,
    source_kind text not null
        check (source_kind in ('registered', 'guest', 'import')),
    -- installation pseudonym: 남용 방어와 진단 전용, 사용자 계정이 아니다.
    installation_key text,
    client_version text,
    payload_version integer,
    received_at timestamptz not null default now(),
    accepted_count integer not null default 0,
    skipped_count integer not null default 0,
    rejected_count integer not null default 0
);

-- rate limit·이상 탐지 확장 경계: installation 단위 최근 batch 조회용.
create index idx_ingestion_batches_installation
    on analytics.ingestion_batches (installation_key, received_at);

-- 거부 이유만 기록하고 거부된 원문 payload는 보존하지 않는다(로드맵 12.2).
create table analytics.rejected_observations (
    id bigint generated always as identity primary key,
    batch_id uuid,
    source_game_id uuid,
    reason text not null,
    received_at timestamptz not null default now()
);

-- 등록 계정 games → 분석 observation projection 트리거(로드맵 6.4).
create or replace function analytics.project_registered_game()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.deleted_at is not null then
        update analytics.duel_observations
        set withdrawn_at = coalesce(withdrawn_at, now()),
            withdrawal_source = coalesce(withdrawal_source, 'registered')
        where source_game_id = new.id;
        return null;
    end if;

    insert into analytics.duel_observations (
        source_game_id,
        contributor_key,
        played_at_local,
        result,
        turn_order,
        my_deck,
        opp_deck,
        turns,
        end_reason,
        play_context_id,
        standing_kind,
        rank_tier_before,
        rank_tier_after,
        rank_division_before,
        rank_division_after,
        rating_before,
        rating_after,
        event_points_before,
        event_points_after,
        payload_version,
        source_kind,
        quality_flags
    )
    values (
        new.id,
        analytics.pseudonym_for(new.user_id::text),
        new.played_at,
        new.result,
        new.turn_order,
        new.my_deck,
        new.opp_deck,
        new.turns,
        new.end_reason,
        new.play_context_id,
        new.standing_kind,
        new.rank_tier_before,
        new.rank_tier_after,
        new.rank_division_before,
        new.rank_division_after,
        new.rating_before,
        new.rating_after,
        new.event_points_before,
        new.event_points_after,
        new.payload_version,
        case when new.source_kind = 'native' then 'registered'
             else new.source_kind end,
        case when new.source_kind = 'import' then array['import']
             else '{}'::text[] end
    )
    on conflict (source_game_id) do update set
        played_at_local = excluded.played_at_local,
        result = excluded.result,
        turn_order = excluded.turn_order,
        my_deck = excluded.my_deck,
        opp_deck = excluded.opp_deck,
        turns = excluded.turns,
        end_reason = excluded.end_reason,
        play_context_id = excluded.play_context_id,
        standing_kind = excluded.standing_kind,
        rank_tier_before = excluded.rank_tier_before,
        rank_tier_after = excluded.rank_tier_after,
        rank_division_before = excluded.rank_division_before,
        rank_division_after = excluded.rank_division_after,
        rating_before = excluded.rating_before,
        rating_after = excluded.rating_after,
        event_points_before = excluded.event_points_before,
        event_points_after = excluded.event_points_after,
        payload_version = excluded.payload_version,
        withdrawn_at = null,
        withdrawal_source = null;
    return null;
end;
$$;

revoke all on function analytics.project_registered_game() from public;

create trigger games_project_observation
    after insert or update on public.games
    for each row
    execute function analytics.project_registered_game();

-- 게스트용 제한된 ingest 함수(로드맵 8.3).
-- Guest Ingest Edge Function만 service_role로 호출한다.
-- 허용 필드 allowlist 밖 key가 있는 observation은 거부하고 이유만 남긴다.
create or replace function analytics.ingest_guest_batch(
    batch_id uuid,
    installation_id uuid,
    client_version text,
    payload_version integer,
    observations jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    allowed_keys constant text[] := array[
        'op', 'sync_id', 'played_at_local', 'timezone_offset_minutes',
        'result', 'turn_order', 'my_deck', 'opp_deck', 'turns', 'end_reason',
        'play_context_id', 'standing_kind',
        'rank_tier_before', 'rank_tier_after',
        'rank_division_before', 'rank_division_after',
        'rating_before', 'rating_after',
        'event_points_before', 'event_points_after',
        'event_id', 'event_stage_id',
        'environment_version_id', 'deck_catalog_version_id'
    ];
    max_batch_size constant integer := 200;
    installation_key text;
    existing analytics.ingestion_batches%rowtype;
    observation jsonb;
    op text;
    sync_id uuid;
    disallowed text;
    reject_reason text;
    accepted integer := 0;
    skipped integer := 0;
    rejected integer := 0;
    inserted_game uuid;
begin
    if batch_id is null or installation_id is null then
        raise exception 'batch_id and installation_id are required'
            using errcode = '22023';
    end if;
    if payload_version is distinct from 1 then
        raise exception 'unsupported payload_version'
            using errcode = '22023';
    end if;
    if observations is null or jsonb_typeof(observations) <> 'array' then
        raise exception 'observations must be a JSON array'
            using errcode = '22023';
    end if;
    if jsonb_array_length(observations) < 1
        or jsonb_array_length(observations) > max_batch_size then
        raise exception 'batch size must be between 1 and %', max_batch_size
            using errcode = '22023';
    end if;

    -- batch idempotency: 같은 batch 재전송은 기록된 요약을 그대로 돌려준다.
    select * into existing
    from analytics.ingestion_batches b
    where b.batch_id = ingest_guest_batch.batch_id;
    if found then
        return jsonb_build_object(
            'batch_id', existing.batch_id,
            'accepted', existing.accepted_count,
            'skipped', existing.skipped_count,
            'rejected', existing.rejected_count,
            'replayed', true
        );
    end if;

    installation_key := analytics.pseudonym_for(installation_id::text);

    for observation in select * from jsonb_array_elements(observations)
    loop
        reject_reason := null;
        sync_id := null;

        if jsonb_typeof(observation) <> 'object' then
            reject_reason := 'observation_not_object';
        else
            -- 허용 필드 allowlist 검사: note, 이메일, 표시 이름 등
            -- private 필드가 포함된 payload는 거부한다.
            select key into disallowed
            from jsonb_object_keys(observation) as t(key)
            where key <> all (allowed_keys)
            limit 1;
            if disallowed is not null then
                reject_reason := 'disallowed_field:' || disallowed;
            end if;
        end if;

        if reject_reason is null then
            begin
                sync_id := (observation ->> 'sync_id')::uuid;
            exception when others then
                reject_reason := 'invalid_sync_id';
            end;
        end if;

        if reject_reason is null then
            op := coalesce(observation ->> 'op', 'create');
            if op = 'withdraw' then
                -- 이미 업로드된 게스트 기록의 철회(로드맵 9.3). idempotent.
                update analytics.duel_observations
                set withdrawn_at = coalesce(withdrawn_at, now()),
                    withdrawal_source = coalesce(withdrawal_source, 'guest')
                where source_game_id = sync_id
                  and source_kind = 'guest';
                if found then
                    accepted := accepted + 1;
                else
                    skipped := skipped + 1;
                end if;
                continue;
            elsif op <> 'create' then
                reject_reason := 'invalid_op';
            end if;
        end if;

        if reject_reason is null then
            begin
                insert into analytics.duel_observations (
                    source_game_id,
                    contributor_key,
                    played_at_local,
                    timezone_offset_minutes,
                    result,
                    turn_order,
                    my_deck,
                    opp_deck,
                    turns,
                    end_reason,
                    play_context_id,
                    standing_kind,
                    rank_tier_before,
                    rank_tier_after,
                    rank_division_before,
                    rank_division_after,
                    rating_before,
                    rating_after,
                    event_points_before,
                    event_points_after,
                    event_id,
                    event_stage_id,
                    environment_version_id,
                    deck_catalog_version_id,
                    client_version,
                    payload_version,
                    source_kind
                )
                values (
                    sync_id,
                    installation_key,
                    observation ->> 'played_at_local',
                    (observation ->> 'timezone_offset_minutes')::integer,
                    observation ->> 'result',
                    observation ->> 'turn_order',
                    observation ->> 'my_deck',
                    observation ->> 'opp_deck',
                    (observation ->> 'turns')::integer,
                    observation ->> 'end_reason',
                    observation ->> 'play_context_id',
                    observation ->> 'standing_kind',
                    observation ->> 'rank_tier_before',
                    observation ->> 'rank_tier_after',
                    (observation ->> 'rank_division_before')::integer,
                    (observation ->> 'rank_division_after')::integer,
                    (observation ->> 'rating_before')::integer,
                    (observation ->> 'rating_after')::integer,
                    (observation ->> 'event_points_before')::integer,
                    (observation ->> 'event_points_after')::integer,
                    observation ->> 'event_id',
                    observation ->> 'event_stage_id',
                    observation ->> 'environment_version_id',
                    observation ->> 'deck_catalog_version_id',
                    ingest_guest_batch.client_version,
                    ingest_guest_batch.payload_version,
                    'guest'
                )
                on conflict (source_game_id) do nothing
                returning source_game_id into inserted_game;

                if inserted_game is null then
                    -- 같은 sync_id observation이 이미 있으면 중복 생성하지 않는다.
                    skipped := skipped + 1;
                else
                    accepted := accepted + 1;
                end if;
            exception when check_violation or invalid_text_representation
                or numeric_value_out_of_range or not_null_violation then
                reject_reason := 'invalid_value';
            end;
        end if;

        if reject_reason is not null then
            rejected := rejected + 1;
            insert into analytics.rejected_observations
                (batch_id, source_game_id, reason)
            values (ingest_guest_batch.batch_id, sync_id, reject_reason);
        end if;
    end loop;

    insert into analytics.ingestion_batches (
        batch_id, source_kind, installation_key, client_version,
        payload_version, accepted_count, skipped_count, rejected_count
    )
    values (
        ingest_guest_batch.batch_id, 'guest', installation_key,
        ingest_guest_batch.client_version, ingest_guest_batch.payload_version,
        accepted, skipped, rejected
    );

    return jsonb_build_object(
        'batch_id', ingest_guest_batch.batch_id,
        'accepted', accepted,
        'skipped', skipped,
        'rejected', rejected,
        'replayed', false
    );
end;
$$;

revoke all on function analytics.ingest_guest_batch(uuid, uuid, text, integer, jsonb)
    from public;

-- PostgREST는 analytics 스키마를 노출하지 않으므로 Edge Function이 호출할
-- public wrapper를 둔다. service_role 전용이며 클라이언트는 실행할 수 없다.
create or replace function public.ingest_guest_batch(
    batch_id uuid,
    installation_id uuid,
    client_version text,
    payload_version integer,
    observations jsonb
)
returns jsonb
language sql
security definer
set search_path = ''
as $$
    select analytics.ingest_guest_batch(
        batch_id, installation_id, client_version, payload_version, observations
    );
$$;

revoke all on function public.ingest_guest_batch(uuid, uuid, text, integer, jsonb)
    from public, anon, authenticated;
grant execute on function public.ingest_guest_batch(uuid, uuid, text, integer, jsonb)
    to service_role;
