import { Suspense } from "react";

import { VideoSearchHome } from "@/components/search/video-search-home";

export default function HomePage() {
  return (
    <Suspense fallback={null}>
      <VideoSearchHome />
    </Suspense>
  );
}
