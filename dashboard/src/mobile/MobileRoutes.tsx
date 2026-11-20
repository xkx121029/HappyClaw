import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { MobileAppShell } from "./MobileAppShell";

const HomePage = lazy(() =>
  import("./pages/HomePage").then((m) => ({ default: m.HomePage })),
);
const ChatPage = lazy(() =>
  import("./pages/ChatPage").then((m) => ({ default: m.ChatPage })),
);
const QuickChatPage = lazy(() =>
  import("./pages/ChatPage").then((m) => ({ default: m.QuickChatPage })),
);
const ExpertsPage = lazy(() =>
  import("./pages/ExpertsPage").then((m) => ({ default: m.ExpertsPage })),
);
const BaoPage = lazy(() =>
  import("./pages/BaoPage").then((m) => ({ default: m.BaoPage })),
);
const TasksPage = lazy(() =>
  import("./pages/TasksPage").then((m) => ({ default: m.TasksPage })),
);
const ConnectorsPage = lazy(() =>
  import("./pages/ConnectorsPage").then((m) => ({ default: m.ConnectorsPage })),
);
const KnowledgePage = lazy(() =>
  import("./pages/KnowledgePage").then((m) => ({ default: m.KnowledgePage })),
);
const UsagePage = lazy(() =>
  import("./pages/UsagePage").then((m) => ({ default: m.UsagePage })),
);
const PersonalizationPage = lazy(() =>
  import("./pages/PersonalizationPage").then((m) => ({
    default: m.PersonalizationPage,
  })),
);
const MorePage = lazy(() =>
  import("./pages/MorePage").then((m) => ({ default: m.MorePage })),
);
const AdminPage = lazy(() =>
  import("./pages/AdminPage").then((m) => ({ default: m.AdminPage })),
);
const NotFoundPage = lazy(() =>
  import("./pages/NotFoundPage").then((m) => ({ default: m.NotFoundPage })),
);

function Loading() {
  return (
    <div className="m-page-scroll">
      <div className="m-page" style={{ paddingTop: 72 }}>
        <div
          className="m-skel"
          style={{ height: 28, width: "46%", borderRadius: 8 }}
        />
        <div className="m-skel" style={{ height: 96, marginTop: 18 }} />
        <div className="m-skel" style={{ height: 96, marginTop: 12 }} />
      </div>
    </div>
  );
}

/**
 * Standalone mobile routes. Mounted only when ``useIsMobile()`` is true, so
 * none of these modules load on desktop.
 */
export function MobileRoutes() {
  return (
    <MobileAppShell>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route index element={<Navigate to="/m/home" replace />} />

          <Route path="/m" element={<Navigate to="/m/home" replace />} />
          <Route path="/m/home" element={<HomePage />} />
          <Route path="/m/quick" element={<QuickChatPage />} />
          <Route path="/m/chat" element={<ChatPage />} />
          <Route path="/m/chat/:agentId" element={<ChatPage />} />
          <Route path="/m/chat/:agentId/:threadId" element={<ChatPage />} />
          <Route path="/m/experts" element={<ExpertsPage />} />
          <Route path="/m/bao" element={<BaoPage />} />
          <Route path="/m/tasks" element={<TasksPage />} />
          <Route path="/m/connectors" element={<ConnectorsPage />} />
          <Route path="/m/knowledge-bases" element={<KnowledgePage />} />
          <Route path="/m/token-usage" element={<UsagePage />} />
          <Route path="/m/personalization" element={<PersonalizationPage />} />
          <Route
            path="/m/personalization/*"
            element={<PersonalizationPage />}
          />
          <Route path="/m/admin" element={<AdminPage />} />
          <Route path="/m/admin/:section" element={<AdminPage />} />
          <Route path="/m/more" element={<MorePage />} />

          {/* Legacy desktop paths keep working on a phone-sized viewport. */}
          <Route path="/home" element={<Navigate to="/m/home" replace />} />
          <Route path="/quick" element={<Navigate to="/m/quick" replace />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/chat/:agentId" element={<ChatPage />} />
          <Route path="/chat/:agentId/:threadId" element={<ChatPage />} />
          <Route
            path="/experts"
            element={<Navigate to="/m/experts" replace />}
          />
          <Route path="/bao" element={<Navigate to="/m/bao" replace />} />
          <Route path="/tasks" element={<Navigate to="/m/tasks" replace />} />
          <Route
            path="/cronjobs"
            element={<Navigate to="/m/tasks" replace />}
          />
          <Route
            path="/connectors"
            element={<Navigate to="/m/connectors" replace />}
          />
          <Route
            path="/knowledge-bases"
            element={<Navigate to="/m/knowledge-bases" replace />}
          />
          <Route
            path="/token-usage"
            element={<Navigate to="/m/token-usage" replace />}
          />
          <Route path="/personalization/*" element={<PersonalizationPage />} />
          <Route path="/admin/*" element={<AdminPage />} />
          <Route path="/skills" element={<Navigate to="/m/more" replace />} />
          <Route
            path="/skill-packages"
            element={<Navigate to="/m/more" replace />}
          />
          <Route
            path="/agent-config"
            element={<Navigate to="/m/more" replace />}
          />
          <Route path="/bridge" element={<Navigate to="/m/more" replace />} />
          <Route path="/acp" element={<Navigate to="/m/more" replace />} />

          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </MobileAppShell>
  );
}
