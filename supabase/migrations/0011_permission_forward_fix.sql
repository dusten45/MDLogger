-- 0011_permission_forward_fix.sql
-- 하드닝 H2 — 서버 권한·경계 forward-fix (B2, M3, H-1, H-2).
--
-- 기존 마이그레이션(0001~0010)을 수정하지 않고 새 마이그레이션으로 보정한다. 적용
-- 전에 `supabase db reset`으로 이전 상태와 동일하게 재구축해 forward-fix 정책을
-- 유지한다(README의 forward-fix 절 참조).

-- ============================================================================
-- B2: 권한 회수 형식 통일.
--   `revoke ... from public`은 암시적 PUBLIC 권한만 제거하며, Supabase
--   부트스트랩의 `ALTER DEFAULT PRIVILEGES ... GRANT ALL ON FUNCTIONS TO
--   anon, authenticated, service_role`로 부여된 명시적 role 권한은 제거하지
--   못한다. 따라서 anon/authenticated를 명시적으로 회수한다.
--   이 4개 함수는 전부 trigger 또는 내부(security definer) 호출로만 실행되므로,
--   소유자(정의자)는 여전히 실행할 수 있고 anon/authenticated의 직접 호출만 차단된다.
-- ============================================================================

-- RPC로 PostgREST에 노출되고 소유권 검사가 없는 쓰기 함수: 반드시 차단.
revoke all on function public.next_game_change_version(uuid)
    from public, anon, authenticated;

-- 공용 updated_at 유지 trigger 함수.
revoke all on function public.set_updated_at()
    from public, anon, authenticated;

-- 등록 games/devices 서버 관리 필드 강제 trigger 함수.
revoke all on function public.enforce_game_server_fields()
    from public, anon, authenticated;
revoke all on function public.enforce_device_server_fields()
    from public, anon, authenticated;

-- ============================================================================
-- M3: 등록 projection이 게스트(또는 다른 출처)의 철회 마커를 조용히 지우지
--   않게 가드한다. 결정 D-1(a): 철회된 description의 `withdrawn_at`/
--   `withdrawal_source`는 어떤 경로로도 다시 null로 만들지 않는다. 출처가
--   게스트인 경우 `source_kind`/`contributor_key`도 유지한다(출처 부지표를
--   내용과 함께 덮어쓰지 않는 최소 보정).
--   기존 0005의 UPDATE SET는 두 철회 컬럼을 무조건 null로 되돌렸다.
-- ============================================================================

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
        payload_version = excluded.payload_version;
        -- M3 가드: `withdrawn_at`/`withdrawal_source`는 SET 하지 않는다.
        -- 철회 마커는 무기한 보존된다(로드맵 결정 6, 9.3).
    return null;
end;
$$;

revoke all on function analytics.project_registered_game() from public;

create or replace function analytics.project_registered_game_timezone()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.deleted_at is null then
        -- 이미 철회된 description은 나중에 어떤 갱신으로도 부지표를 바꿀 수
        -- 없도록, 아직 철회되지 않은 행에만 timezone을 반영한다(M3 가드).
        update analytics.duel_observations
        set timezone_offset_minutes = new.timezone_offset_minutes
        where source_game_id = new.id
          and withdrawn_at is null;
    end if;
    return null;
end;
$$;

revoke all on function analytics.project_registered_game_timezone() from public;

-- ============================================================================
-- H-1: RLS 미활성 테이블에 RLS를 활성화한다(기본 전면 거부).
--   - `security definer` 함수는 테이블 소유자로 실행되므로 그대로 동작한다.
--   - 별도 정책을 만들지 않아 클라이언트(anon/authenticated)는 계속 접근 불가.
--   - `public.game_change_cursors`는 public 스키마라 Supabase linter 대상이며
--     단일 grant 실수에도 방어가 되도록 RLS를 켠다.
-- ============================================================================

alter table analytics.contributor_salt enable row level security;
alter table analytics.duel_observations enable row level security;
alter table analytics.ingestion_batches enable row level security;
alter table analytics.rejected_observations enable row level security;
alter table public.game_change_cursors enable row level security;

-- ============================================================================
-- H-2: `public.profiles` 서버 관리 필드 강제(결정 D-2(a)).
--   - anon/authenticated의 기존 grant와 RLS 정책(0001/0003)을 유지한다.
--   - BEFORE INSERT OR UPDATE 트리거가 `id`를 auth.uid()로, `created_at`을
--     INSERT 시 now()로, `updated_at`을 now()로 고정하고, UPDATE에서는
--     `created_at`을 불변으로 유지해 클라이언트 위조를 차단한다.
--   - `auth.uid()`가 없는 실행자(예: service_role)에서는 제공된 `id`를 유지한다.
-- ============================================================================

create or replace function public.enforce_profile_server_fields()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    new.id := coalesce((select auth.uid()), new.id);
    if tg_op = 'INSERT' then
        new.created_at := now();
    else
        new.created_at := old.created_at;
    end if;
    new.updated_at := now();
    return new;
end;
$$;

revoke all on function public.enforce_profile_server_fields()
    from public, anon, authenticated;

create trigger profiles_enforce_server_fields
    before insert or update on public.profiles
    for each row
    execute function public.enforce_profile_server_fields();
