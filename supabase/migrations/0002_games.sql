-- 0002_games.sql
-- 등록 계정의 개인용 games 테이블과 장치(devices) 테이블.
-- 로컬 naive ISO `played_at` 형식을 그대로 보존한다(로드맵 7.3).
-- `change_version` 부여와 서버 관리 필드 보호 트리거는 0004에서 추가한다.

create table public.games (
    -- 클라이언트가 생성한 장치 독립 UUID(로컬 games.sync_id).
    id uuid primary key,
    user_id uuid not null references auth.users (id) on delete cascade,

    -- 기존 로컬 필드: 현재 의미를 유지한다.
    played_at text not null
        check (played_at ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$'),
    result text not null check (result in ('win', 'lose')),
    turn_order text not null check (turn_order in ('first', 'second')),
    my_deck text,
    opp_deck text,
    turns integer check (turns is null or turns >= 0),
    end_reason text,
    -- 레거시 WCQ 누적 점수. 단계 9 migration 전까지 현재 의미를 유지한다.
    score_after integer,
    -- 개인용 자유 메모. 분석 projection에서 제외된다(로드맵 6.2).
    note text,

    -- 플레이 문맥과 점수 체계(로드맵 7.5). 기준정보는 소유자가 관리한다.
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
    -- 대회(2라운드) 점수는 0 시작이지만 상한 validation을 두지 않는다.
    event_points_before integer check (event_points_before is null
                                       or event_points_before >= 0),
    event_points_after integer check (event_points_after is null
                                      or event_points_after >= 0),

    -- 서버 관리 필드: 0004 트리거가 클라이언트 값을 무시하고 강제한다.
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz,
    change_version bigint not null default 0,
    payload_version integer not null default 1 check (payload_version >= 1),
    source_kind text not null default 'native'
        check (source_kind in ('native', 'guest', 'import'))
);

comment on table public.games is
    '등록 계정의 개인용 듀얼 기록. 삭제는 deleted_at tombstone으로만 전파한다.';
comment on column public.games.note is
    '개인용 자유 메모. 분석 projection으로 복제하지 않는다.';
comment on column public.games.change_version is
    '서버가 부여하는 단조 증가 버전. 클라이언트가 설정할 수 없다.';

create index idx_games_user_change_version
    on public.games (user_id, change_version);

alter table public.games enable row level security;

-- 물리 DELETE는 클라이언트에 허용하지 않는다. 개인 기록 삭제는
-- deleted_at tombstone UPDATE로만 전파한다(로드맵 9.3).
revoke all on table public.games from anon, authenticated;
grant select, insert, update on table public.games to authenticated;

-- 장치 등록: tombstone 보존 판단과 동기화 진단에 사용한다(로드맵 결정 6, C).
create table public.devices (
    id uuid primary key,
    user_id uuid not null references auth.users (id) on delete cascade,
    installation_id uuid not null,
    display_name text,
    client_version text,
    created_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    -- 이 장치가 pull로 확인한 마지막 change_version.
    last_acknowledged_version bigint not null default 0
        check (last_acknowledged_version >= 0),
    unique (user_id, installation_id)
);

comment on table public.devices is
    '등록 계정이 로그인한 장치. tombstone 정리 판단과 진단에만 사용한다.';

alter table public.devices enable row level security;

revoke all on table public.devices from anon, authenticated;
grant select, insert, update on table public.devices to authenticated;
