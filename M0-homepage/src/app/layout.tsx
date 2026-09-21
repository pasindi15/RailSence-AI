import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RailSense AI — Intelligent Railway System",
  description:
    "RailSense AI is a 4-agent intelligent railway system for Sri Lanka Railways, built as part of IT3041.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
