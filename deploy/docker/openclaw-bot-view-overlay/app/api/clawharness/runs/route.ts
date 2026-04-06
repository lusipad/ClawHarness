import { NextResponse } from "next/server";

function buildHeaders() {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token =
    process.env.HARNESS_API_TOKEN?.trim() ||
    process.env.HARNESS_READONLY_TOKEN?.trim();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

function requireHarnessBaseUrl() {
  const baseUrl = process.env.HARNESS_BASE_URL?.trim();
  if (!baseUrl) {
    throw new Error("HARNESS_BASE_URL is not configured");
  }
  return baseUrl.replace(/\/$/, "");
}

export async function GET(request: Request) {
  try {
    const baseUrl = requireHarnessBaseUrl();
    const url = new URL(request.url);
    const limit = url.searchParams.get("limit") || "50";
    const status = url.searchParams.get("status");
    const taskKey = url.searchParams.get("task_key");

    const upstream = new URL(`${baseUrl}/api/runs`);
    upstream.searchParams.set("limit", limit);
    if (status) {
      upstream.searchParams.set("status", status);
    }
    if (taskKey) {
      upstream.searchParams.set("task_key", taskKey);
    }

    const response = await fetch(upstream, {
      headers: buildHeaders(),
      cache: "no-store",
    });
    const text = await response.text();
    return new NextResponse(text, {
      status: response.status,
      headers: { "content-type": response.headers.get("content-type") || "application/json" },
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: "clawharness_proxy_failed",
        detail: error instanceof Error ? error.message : String(error),
      },
      { status: 500 },
    );
  }
}
