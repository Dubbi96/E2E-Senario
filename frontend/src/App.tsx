import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { RequireAuth } from './components/RequireAuth'
import { LoginPage } from './pages/LoginPage'
import { RegisterPage } from './pages/RegisterPage'
import { DashboardPage } from './pages/DashboardPage'
import { MyScenariosPage } from './pages/MyScenariosPage'
import { ScenarioEditorPage } from './pages/ScenarioEditorPage'
import { TeamsPage } from './pages/TeamsPage'
import { TeamDetailPage } from './pages/TeamDetailPage'
import { SuiteRunsPage } from './pages/SuiteRunsPage'
import { SuiteRunDetailPage } from './pages/SuiteRunDetailPage'
import { RunsPage } from './pages/RunsPage'
import { AuthStatesPage } from './pages/AuthStatesPage'
import { WebRecorderPage } from './pages/WebRecorderPage'
import { WebRecorderInstallPage } from './pages/WebRecorderInstallPage'
import { LandingPage } from './pages/LandingPage'

export default function App() {
  return (
    <Routes>
      {/* Public (no backoffice shell) */}
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/recorder/install" element={<WebRecorderInstallPage />} />

      {/* App (backoffice shell) */}
      <Route element={<Layout />}>
        <Route
          path="/dashboard"
          element={
            <RequireAuth>
              <DashboardPage />
            </RequireAuth>
          }
        />

        <Route
          path="/scenarios"
          element={
            <RequireAuth>
              <MyScenariosPage />
            </RequireAuth>
          }
        />
        <Route
          path="/scenarios/:scenarioId"
          element={
            <RequireAuth>
              <ScenarioEditorPage />
            </RequireAuth>
          }
        />

        <Route
          path="/teams"
          element={
            <RequireAuth>
              <TeamsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/teams/:teamId"
          element={
            <RequireAuth>
              <TeamDetailPage />
            </RequireAuth>
          }
        />

        <Route
          path="/suite-runs"
          element={
            <RequireAuth>
              <SuiteRunsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/suite-runs/:suiteRunId"
          element={
            <RequireAuth>
              <SuiteRunDetailPage />
            </RequireAuth>
          }
        />

        <Route
          path="/runs"
          element={
            <RequireAuth>
              <RunsPage />
            </RequireAuth>
          }
        />

        <Route
          path="/auth-states"
          element={
            <RequireAuth>
              <AuthStatesPage />
            </RequireAuth>
          }
        />

        <Route
          path="/recorder"
          element={
            <RequireAuth>
              <WebRecorderPage />
            </RequireAuth>
          }
        />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
