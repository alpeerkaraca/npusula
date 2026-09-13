import React, { useState } from "react";
import { Search, UserRound } from "lucide-react";
export default function Topbar({ goToPage }) {
  const [query, setQuery] = useState("");
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
      <button className="operator" onClick={() => goToPage("setup")}>
        <span>
          <UserRound size={18} />
        </span>
        Operatör
      </button>
    </header>
  );
}
