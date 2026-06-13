"use client";

import { useEffect, useState } from "react";

export function TypewriterText({
  text,
  speed = 25,
  cursorClassName = "obs-typewriter-cursor",
}: {
  text: string;
  speed?: number;
  cursorClassName?: string;
}) {
  const [displayedText, setDisplayedText] = useState("");

  useEffect(() => {
    setDisplayedText("");
    if (!text) return;

    let currentIndex = 0;
    const intervalId = setInterval(() => {
      setDisplayedText(() => {
        const nextContent = text.slice(0, currentIndex + 1);
        currentIndex++;
        if (currentIndex >= text.length) {
          clearInterval(intervalId);
        }
        return nextContent;
      });
    }, speed);

    return () => clearInterval(intervalId);
  }, [text, speed]);

  return (
    <span>
      {displayedText}
      {displayedText.length < text.length && (
        <span className={cursorClassName} />
      )}
    </span>
  );
}
