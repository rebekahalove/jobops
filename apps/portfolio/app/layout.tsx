import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Rebekah Love | Candidate Agent",
  description: "Grounded candidate-agent portfolio powered by JobOps."
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
