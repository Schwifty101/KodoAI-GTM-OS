import { createClient } from "@supabase/supabase-js";

// Browser client: the publishable key plus the operator's login. RLS decides what it can read.
// The secret key never appears in this app.
export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
);
