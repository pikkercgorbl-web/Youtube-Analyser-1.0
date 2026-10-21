"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { User } from "lucide-react";

import { CompetitorMultiHome } from "@/components/mass-analysis/competitor-multi-home";
import { buildChannelSingleAnalysisFromRefUrl } from "@/lib/channel-single-analysis-url";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export default function MassAnalysisPage() {
  const router = useRouter();
  const [singleRef, setSingleRef] = useState("");

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <User className="h-4 w-4" />
            Один канал
          </CardTitle>
          <CardDescription>
            Ссылка, @handle или UC… — публикации автора и сравнение выбранного ролика.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 sm:flex-row">
          <Input
            placeholder="https://youtube.com/@channel или UCxxxxxxxx"
            value={singleRef}
            onChange={(e) => setSingleRef(e.target.value)}
          />
          <Button
            type="button"
            variant="secondary"
            disabled={!singleRef.trim()}
            onClick={() => router.push(buildChannelSingleAnalysisFromRefUrl(singleRef))}
          >
            Анализ канала
          </Button>
        </CardContent>
      </Card>

      <CompetitorMultiHome />
    </div>
  );
}
