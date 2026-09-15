import React, { useState } from "react";
import { Search } from "lucide-react";
import AccountPicker from "./AccountPicker.jsx";
import { usePusula } from "../../features/pusula/PusulaProvider.jsx";
export default function Topbar({ goToPage }) {
  const [query, setQuery] = useState("");
  // Topbar renders inside PusulaProvider (App.jsx), so the active account and
  // the switch handler come straight from the context.
  const ui = usePusula();
  return (
    <header className="app-topbar">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          goToPage("explore");
        }}
      >
        <Search size={19} />
        <input
          aria-label="Arama yap"
          placeholder="Arama yap..."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </form>
      <AccountPicker
        userId={ui.userId}
        users={ui.sampleUsers}
        onSelect={ui.chooseUser}
        onNewUser={ui.chooseNewUser}
      />
    </header>
  );
}
