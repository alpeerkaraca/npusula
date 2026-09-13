import {
  Home,
  Bell,
  MessageCircle,
  Compass,
  Gamepad2,
  Users,
  Bookmark,
  Heart,
  Rocket,
} from "lucide-react";
export const NAV_ITEMS = [
  { id: "home", icon: Home, label: "Ana Sayfa" },
  { id: "notifications", icon: Bell, label: "Bildirimler", showBadge: true },
  { id: "messages", icon: MessageCircle, label: "Mesajlar" },
  { id: "explore", icon: Compass, label: "Keşfet" },
  { id: "play", icon: Gamepad2, label: "Nod Oyna" },
  { id: "communities", icon: Users, label: "Topluluklar" },
  { id: "saved", icon: Bookmark, label: "Kaydedilenler" },
  { id: "likes", icon: Heart, label: "Beğeniler" },
  { id: "teknofest", icon: Rocket, label: "TEKNOFEST Kayıt" },
];
