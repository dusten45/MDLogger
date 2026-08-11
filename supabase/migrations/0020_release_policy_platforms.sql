-- 0020_release_policy_platforms.sql
-- 하드닝 H3 forward-fix — macOS/Linux 플랫폼의 release policy 행 추가.
--
-- 0012는 windows 행만 시드해, macOS/Linux에서 실행하는 클라이언트가 자기
-- 플랫폼 정책을 조회해도 행이 없어 최소 지원 버전 등의 정책이 적용되지 못했다.
-- 클라이언트는 이제 실제 OS를 감지해 해당 플랫폼의 정책을 조회하므로(하드닝 H3),
-- 결정 D-7(최소=최신=0.1.6)에 맞춰 macOS/Linux 행을 추가한다.
-- 이미 존재하면 중복 삽입하지 않는다(멱등).

insert into public.release_policies (
    platform, latest_version, minimum_supported_version,
    notice, update_url, effective_at,
    payload_version_min, payload_version_max,
    sync_schema_version_min, sync_schema_version_max,
    block_online, block_local_writes, allow_export
)
values
    ('linux', '0.1.6', '0.1.6', null, '', now(), 1, 1, 1, 1, true, false, true),
    ('macos', '0.1.6', '0.1.6', null, '', now(), 1, 1, 1, 1, true, false, true)
on conflict (platform) do nothing;
