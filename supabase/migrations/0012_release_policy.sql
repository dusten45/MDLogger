-- 0012_release_policy.sql
-- 하드닝 H3 — release policy와 클라이언트 버전 정책(로드맵 §2.7, 결정 14,
-- §17.3.J). 배포 킬 스위치와 최소 지원 버전 강제의 기준 테이블.
--
-- 최소 지원 버전은 코드에 고정하지 않는다. 서버 정책에서 변경할 수 있다.
-- 클라이언트는 이 테이블을 읽어 온라인 시작 예외 처리를 결정하고, 마지막으로
-- 받은 정책을 로컬에 캐시해 오프라인에서도 같은 판정을 유지한다.

create table public.release_policies (
    platform text primary key
        check (platform in ('windows', 'macos', 'linux')),
    -- 사용자에게 표시할 최신 버전과 최소 지원 버전(신규: v0.1.6).
    latest_version text not null,
    minimum_supported_version text not null,
    -- 업데이트 안내 문구. null이면 기본 안내를 사용한다.
    notice text,
    -- 공식 다운로드/배포 위치. 소유자 운영 값(로드맵 17.2).
    update_url text,
    -- 이 정책이 유효해지는 시점. 이전 캐시보다 나중인 정책만 적용한다.
    effective_at timestamptz not null default now(),
    -- 호환 payload/sync schema version 범위(포괄). 현재는 1만 지원.
    payload_version_min integer not null default 1,
    payload_version_max integer not null default 1,
    sync_schema_version_min integer not null default 1,
    sync_schema_version_max integer not null default 1,
    -- 최소 지원 미만 클라이언트의 온라인 동작을 차단한다.
    block_online boolean not null default true,
    -- (예약) 정책상 로컬 신규 기록을 막을지. 현재 구현에서는 항상 false.
    block_local_writes boolean not null default false,
    -- 데이터 탈출 경로 보장: 내보내기는 정책상 항상 허용한다(로드맵 17.3.J).
    allow_export boolean not null default true
);

comment on table public.release_policies is
    '클라이언트 릴리스 정책. 읽기 전용 공개 조회, 클라이언트 수정 금지(RLS).';

-- RLS 활성화 + 읽기 전용 노출(D-3(a)): anon/authenticated는 SELECT만 가능.
alter table public.release_policies enable row level security;

revoke all on table public.release_policies from anon, authenticated;
grant select on table public.release_policies to anon, authenticated;

create policy release_policies_select_public
    on public.release_policies
    for select
    to anon, authenticated
    using (true);

-- 정책 시드(결정 D-7 확정): 프로젝트가 이전 버전과 크게 달라져 0.1.6이
-- 유일한 버전이다. 따라서 **최소 지원 = 최신 = 0.1.6**이며, 0.1.6 미만은 온라인에서
-- 차단된다. 당장 마이그레이션할 업데이트가 없으므로 update_url은 비워 둔다.
-- 이후 업데이트가 생기면 이 행의 latest/minimum/update_url을 갱신한다.
insert into public.release_policies (
    platform, latest_version, minimum_supported_version,
    notice, update_url, effective_at,
    payload_version_min, payload_version_max,
    sync_schema_version_min, sync_schema_version_max,
    block_online, block_local_writes, allow_export
)
values (
    'windows', '0.1.6', '0.1.6',
    null, '',
    now(),
    1, 1, 1, 1,
    true, false, true
);
