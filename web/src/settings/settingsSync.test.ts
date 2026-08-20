import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/supabase", () => ({
    getSupabaseClient: vi.fn(),
}));

import { getSupabaseClient } from "../lib/supabase";
import { DEFAULT_SETTINGS } from "./webSettings";
import { downloadPreferences, uploadPreferences } from "./settingsSync";

const mockRpc = vi.fn();
const mockFrom = vi.fn();

beforeEach(() => {
    mockRpc.mockReset();
    mockFrom.mockReset();
    vi.mocked(getSupabaseClient).mockReturnValue({
        rpc: mockRpc,
        from: mockFrom,
    } as never);
});

describe("settingsSync", () => {
    it("uploadPreferences는 PREFERENCE_KEYS만 전송한다", async () => {
        mockRpc.mockResolvedValue({ data: {}, error: null });

        await uploadPreferences({
            ...DEFAULT_SETTINGS,
            theme_mode: "dark",
            accent_color: "teal",
            memo_enabled: false,
            default_mode: "rank-2026-08",
            score_input_mode: "direct",
            font_scale: 1.5,
        });

        expect(mockRpc).toHaveBeenCalledWith("upsert_user_settings", {
            preferences: {
                theme_mode: "dark",
                accent_color: "teal",
                memo_enabled: false,
                default_mode: "rank-2026-08",
                score_input_mode: "direct",
            },
        });
    });

    it("uploadPreferences 실패 시 오류를 던진다", async () => {
        mockRpc.mockResolvedValue({ data: null, error: new Error("denied") });

        await expect(uploadPreferences(DEFAULT_SETTINGS)).rejects.toThrow(
            "denied",
        );
    });

    it("downloadPreferences는 PREFERENCE_KEYS만 취하고 DEVICE_KEYS를 제거한다", async () => {
        const select = vi.fn().mockResolvedValue({
            data: [
                {
                    preferences: {
                        theme_mode: "light",
                        accent_color: "amber",
                        memo_enabled: true,
                        default_mode: "last_used",
                        score_input_mode: "delta",
                        font_scale: 1.5,
                    },
                },
            ],
            error: null,
        });
        mockFrom.mockReturnValue({ select });

        const patch = await downloadPreferences();

        expect(patch).toEqual({
            theme_mode: "light",
            accent_color: "amber",
            memo_enabled: true,
            default_mode: "last_used",
            score_input_mode: "delta",
        });
    });

    it("downloadPreferences는 행이 없으면 null을 반환한다", async () => {
        const select = vi.fn().mockResolvedValue({ data: [], error: null });
        mockFrom.mockReturnValue({ select });

        await expect(downloadPreferences()).resolves.toBeNull();
    });
});
