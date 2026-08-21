import { useEffect, useState } from "react";

export interface BeforeInstallPromptEvent extends Event {
    readonly platforms: string[];
    readonly userChoice: Promise<{
        outcome: "accepted" | "dismissed";
        platform: string;
    }>;
    prompt(): Promise<void>;
}

export function checkIsStandalone(): boolean {
    if (typeof window === "undefined") {
        return false;
    }
    const isStandaloneMedia = window.matchMedia(
        "(display-mode: standalone)",
    ).matches;
    const isIOSStandalone =
        (navigator as unknown as { standalone?: boolean }).standalone === true;
    return isStandaloneMedia || isIOSStandalone;
}

export function checkIsIOS(): boolean {
    if (typeof navigator === "undefined") {
        return false;
    }
    const isStandardIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
    const isIPadOS =
        navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
    const isMSStream = Boolean(
        (window as unknown as { MSStream?: unknown }).MSStream,
    );
    return (isStandardIOS || isIPadOS) && !isMSStream;
}

export interface UseInstallPromptResult {
    canInstall: boolean;
    isStandalone: boolean;
    isIOS: boolean;
    promptInstall: () => Promise<boolean>;
}

export function useInstallPrompt(): UseInstallPromptResult {
    const [deferredPrompt, setDeferredPrompt] =
        useState<BeforeInstallPromptEvent | null>(null);
    const [isStandalone, setIsStandalone] = useState<boolean>(() =>
        checkIsStandalone(),
    );
    const [isIOS] = useState<boolean>(() => checkIsIOS());

    useEffect(() => {
        setIsStandalone(checkIsStandalone());

        function handleBeforeInstallPrompt(event: Event) {
            event.preventDefault();
            setDeferredPrompt(event as BeforeInstallPromptEvent);
        }

        function handleAppInstalled() {
            setDeferredPrompt(null);
            setIsStandalone(true);
        }

        window.addEventListener(
            "beforeinstallprompt",
            handleBeforeInstallPrompt,
        );
        window.addEventListener("appinstalled", handleAppInstalled);

        return () => {
            window.removeEventListener(
                "beforeinstallprompt",
                handleBeforeInstallPrompt,
            );
            window.removeEventListener("appinstalled", handleAppInstalled);
        };
    }, []);

    async function promptInstall(): Promise<boolean> {
        if (!deferredPrompt) {
            return false;
        }

        try {
            await deferredPrompt.prompt();
            const choiceResult = await deferredPrompt.userChoice;
            setDeferredPrompt(null);
            return choiceResult.outcome === "accepted";
        } catch (error) {
            console.error("Install prompt error:", error);
            setDeferredPrompt(null);
            return false;
        }
    }

    return {
        canInstall: deferredPrompt !== null && !isStandalone,
        isStandalone,
        isIOS,
        promptInstall,
    };
}
