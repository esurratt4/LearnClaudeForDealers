// ============================================================================
//  TEMPLATE - COPY THIS FILE BEFORE YOU EDIT IT
//
//      cp dashboard/config.example.js dashboard/config.js
//
//  Then open dashboard/config.js and paste your own values in. This example
//  file IS committed to git; config.js is not, because it holds your key.
// ============================================================================
//
//  WHERE THE VALUES COME FROM
//    1. Go to https://supabase.com and open your project.
//    2. Click the gear icon (Project Settings) in the left sidebar.
//    3. Click "API".
//    4. Copy "Project URL"  ->  supabaseUrl below.
//    5. Copy the key labelled "anon" / "public"  ->  supabaseAnonKey below.
//
//  READ THIS BEFORE YOU COPY A KEY
//  Supabase shows you two keys on that page and they are not interchangeable:
//
//    anon / public   Read-only here. sql/schema.sql grants it SELECT on the
//                    reports and nothing else. This is the one that goes in a
//                    browser. Anyone who opens the dashboard can see it, and
//                    that is fine - the worst they can do is look.
//
//    service_role    Full write and delete access, and it IGNORES every
//                    security rule in the database. The scraper uses it, from
//                    your .env file. If you ever paste it here, anyone who
//                    loads the page can wipe your database. The dashboard
//                    actually checks for this and refuses to run.
//
//  Rule of thumb: if a file is downloaded by a browser, it gets the anon key.
// ============================================================================

window.DASHBOARD_CONFIG = {
  // Looks like https://abcdefghijklmnop.supabase.co
  supabaseUrl: "PASTE_YOUR_PROJECT_URL_HERE",

  // The long "anon" / "public" key. It starts with "eyJ".
  supabaseAnonKey: "PASTE_YOUR_ANON_KEY_HERE",

  // The headline at the top of the dashboard.
  dealershipName: "My Dealership",
};
