import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

function requireHarnessBaseUrl() {
  const baseUrl = process.env.HARNESS_BASE_URL?.trim();
  if (!baseUrl) {
    throw new Error("HARNESS_BASE_URL is not configured");
  }
  return baseUrl.replace(/\/$/, "");
}

function buildHeaders() {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  const token = process.env.HARNESS_CONTROL_TOKEN?.trim();
  if (!token) {
    throw new Error("HARNESS_CONTROL_TOKEN is not configured");
  }
  headers.Authorization = `Bearer ${token}`;
  return headers;
}

export async function POST(
  request: Request,
  context: { params: Promise<{ runId: string }> },
) {
  try {
    const { runId } = await context.params;
    const baseUrl = requireHarnessBaseUrl();
    const payload = await request.json();
    const response = await fetch(`${baseUrl}/api/runs/${encodeURIComponent(runId)}/command`, {
      method: "POST",
      headers: buildHeaders(),
      body: JSON.stringify(payload),
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
        error: "clawharness_control_proxy_failed",
        detail: error instanceof Error ? error.message : String(error),
      },
      { status: 500 },
    );
  }
}
