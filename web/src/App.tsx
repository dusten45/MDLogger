import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthProvider";
import { AppShell } from "./components/AppShell";
import { RequireAuth } from "./components/RequireAuth";
import { AuthCallbackPage } from "./routes/AuthCallbackPage";
import { HistoryPage } from "./routes/HistoryPage";
import { LoginPage } from "./routes/LoginPage";
import { RecordPage } from "./routes/RecordPage";
import { SettingsPage } from "./routes/SettingsPage";
import { StatsPage } from "./routes/StatsPage";

export default function App() {
    return (
        <AuthProvider>
            <BrowserRouter>
                <Routes>
                    <Route
                        element={
                            <RequireAuth>
                                <AppShell />
                            </RequireAuth>
                        }
                    >
                        <Route index element={<RecordPage />} />
                        <Route path="stats" element={<StatsPage />} />
                        <Route path="history" element={<HistoryPage />} />
                        <Route path="settings" element={<SettingsPage />} />
                    </Route>
                    <Route path="login" element={<LoginPage />} />
                    <Route
                        path="auth/callback"
                        element={<AuthCallbackPage />}
                    />
                    <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
            </BrowserRouter>
        </AuthProvider>
    );
}
