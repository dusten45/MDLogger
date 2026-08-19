-- v0.2.1 is a compatible UI patch: advertise it while keeping v0.2.0 supported.
update public.release_policies
set latest_version = '0.2.1',
    minimum_supported_version = '0.2.0',
    effective_at = now()
where platform in ('windows', 'macos', 'linux');
