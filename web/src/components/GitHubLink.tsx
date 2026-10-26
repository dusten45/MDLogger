import "./GitHubLink.css";

export function GitHubLink() {
    return (
        <a
            className="github-link"
            href="https://github.com/dusten45/MDLogger"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="MDLogger GitHub 저장소 (새 탭에서 열림)"
            title="MDLogger GitHub 저장소 (새 탭에서 열림)"
        >
            <img
                className="github-link__icon--light"
                src="/github-invertocat-black.svg"
                alt=""
                width="32"
                height="32"
            />
            <img
                className="github-link__icon--dark"
                src="/github-invertocat-white.svg"
                alt=""
                width="32"
                height="32"
            />
        </a>
    );
}
