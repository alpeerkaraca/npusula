import React, { useState } from "react";
import "./styles/layout.css";
import "./styles/stitch.css";
import "./styles/social-reference.css";
import "./styles/pusula-social.css";
import { PusulaProvider } from "./features/pusula/PusulaProvider.jsx";
import PusulaPage, { PUSULA_PAGES } from "./features/pusula/PusulaPage.jsx";
import Topbar from "./components/layout/Topbar.jsx";
import { ThemeProvider, useTheme } from "./theme/ThemeProvider.jsx";
import { useFeedState } from "./features/feed/useFeedState.js";
import Sidebar from "./components/layout/Sidebar.jsx";
import RightSidebar from "./components/layout/RightSidebar.jsx";
import MessagesBar from "./features/messages/MessagesBar.jsx";
import HomePage from "./pages/HomePage.jsx";
import MessagesPage from "./pages/MessagesPage.jsx";
import SettingsPage from "./pages/SettingsPage.jsx";
import NotificationsPage from "./pages/NotificationsPage.jsx";
import ExplorePage from "./pages/ExplorePage.jsx";
import GamesPage from "./pages/GamesPage.jsx";
import CommunitiesPage from "./pages/CommunitiesPage.jsx";
import SavedPage from "./pages/SavedPage.jsx";
import LikesPage from "./pages/LikesPage.jsx";
import TeknofestPage from "./pages/TeknofestPage.jsx";

function SocialApp() {
  const { bg, border, textPrimary } = useTheme();
  const [activePage, setActivePage] = useState("home");
  const [mediaOnly, setMediaOnly] = useState(false);
  const [messagesOpen, setMessagesOpen] = useState(true);
  const [openConversation, setOpenConversation] = useState(null);
  const {
    tab,
    setTab,
    draft,
    setDraft,
    expanded,
    setExpanded,
    postState,
    toggleLike,
    toggleRepost,
    toggleCommentBox,
    setCommentDraft,
    submitComment,
  } = useFeedState();
  function goToPage(id) {
    setActivePage(id);
    setOpenConversation(null);
  }
  const isPusula = PUSULA_PAGES.some(([id]) => id === activePage);
  const socialDark = bg !== "#f5f6f8";
  return (
    <PusulaProvider
      navigate={goToPage}
      draft={draft}
      setDraft={setDraft}
      activePage={activePage}
    >
      <div
        className={`app-shell stitch-shell social-shell ${isPusula ? "pusula-shell" : ""} ${bg === "#f5f6f8" ? "light-theme" : "dark"}`}
        style={{
          "--app-bg": socialDark ? "#1c1f26" : bg,
          "--app-border": border,
          color: textPrimary,
          fontFamily:
            "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        }}
      >
        <Sidebar
          activePage={isPusula ? "assistant" : activePage}
          goToPage={goToPage}
          mediaOnly={mediaOnly}
          setMediaOnly={setMediaOnly}
        />

        <main className="main-content">
          {isPusula && <Topbar goToPage={goToPage} />}
          {activePage === "home" && (
            <HomePage
              tab={tab}
              setTab={setTab}
              draft={draft}
              setDraft={setDraft}
              expanded={expanded}
              setExpanded={setExpanded}
              postState={postState}
              toggleLike={toggleLike}
              toggleRepost={toggleRepost}
              toggleCommentBox={toggleCommentBox}
              setCommentDraft={setCommentDraft}
              submitComment={submitComment}
            />
          )}
          {activePage === "messages" && (
            <MessagesPage
              openConversation={openConversation}
              setOpenConversation={setOpenConversation}
            />
          )}
          {activePage === "settings" && (
            <SettingsPage mediaOnly={mediaOnly} setMediaOnly={setMediaOnly} />
          )}
          {activePage === "notifications" && <NotificationsPage />}
          {activePage === "explore" && <ExplorePage />}
          {activePage === "play" && <GamesPage />}
          {activePage === "communities" && <CommunitiesPage />}
          {activePage === "saved" && <SavedPage />}
          {activePage === "likes" && <LikesPage />}
          {activePage === "teknofest" && <TeknofestPage />}
          {isPusula && <PusulaPage page={activePage} />}
        </main>
        <RightSidebar isPusula={isPusula} goToPage={goToPage} />
        <MessagesBar
          messagesOpen={messagesOpen}
          setMessagesOpen={setMessagesOpen}
        />
      </div>
    </PusulaProvider>
  );
}
export default function App() {
  return (
    <ThemeProvider>
      <SocialApp />
    </ThemeProvider>
  );
}