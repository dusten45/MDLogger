// 웹 배포 build ID/git commit (spec §3.2, P18).
// 데스크톱 SemVer와 별개로, CI/CD가 VITE_BUILD_ID에 실제 git commit을 주입한다.
export const CLIENT_VERSION = import.meta.env.VITE_BUILD_ID ?? "web-dev";
