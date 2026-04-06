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

export async function GET(
  _request: Request,
  context: { params: Promise<{ runId: string }> },
) {
  try {
    const { runId } = await context.params;
    const baseUrl = requireHarnessBaseUrl();
    const response = await fetch(`${baseUrl}/api/runs/${encodeURIComponent(runId)}/graph`, {
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
