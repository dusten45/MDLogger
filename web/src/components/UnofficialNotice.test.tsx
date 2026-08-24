import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
    ENGLISH_UNOFFICIAL_NOTICE,
    KOREAN_UNOFFICIAL_NOTICE,
    UnofficialNotice,
} from "./UnofficialNotice";

describe("UnofficialNotice", () => {
    it("비공식 관계와 권리 고지문을 정확히 표시한다", () => {
        render(<UnofficialNotice />);

        const notice = screen.getByRole("note", {
            name: "비공식 도구 및 권리 관계 안내",
        });
        expect(notice).toHaveTextContent(KOREAN_UNOFFICIAL_NOTICE);
        expect(notice).toHaveTextContent(ENGLISH_UNOFFICIAL_NOTICE);
    });
});
