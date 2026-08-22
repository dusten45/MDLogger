-- v1.0.0 is the official release: minimum and latest version are both 1.0.0.
update public.release_policies
set latest_version = '1.0.0',
    minimum_supported_version = '1.0.0',
    effective_at = now()
where platform in ('windows', 'macos', 'linux');
