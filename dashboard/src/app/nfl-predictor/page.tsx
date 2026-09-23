import { redirect } from "next/navigation";

// Emit an HTTP Location header at request time, not a cached static 307 shell.
export const dynamic = "force-dynamic";

export default function NflPredictorRedirect() {
  redirect("/experimental");
}
