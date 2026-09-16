// ============================================================================
//  DASHBOARD SETTINGS - TEMPLATE
//
//  Copy this file to dashboard/config.js and fill in your own values:
//
//      cp dashboard/config.example.js dashboard/config.js
//
//  This example file IS committed to git. config.js is NOT (it is in .gitignore),
//  because it points at YOUR database.
// ============================================================================
//
//  WHERE THE VALUES COME FROM (supabase.com, open your project)
//    supabaseUrl      Project Settings > Data API > Project URL
//    supabaseAnonKey  Project Settings > API Keys > the "anon" / "public" key
//
//  USE THE ANON KEY, NOT THE SERVICE_ROLE KEY
//    anon          Read-only. sql/schema.sql lets it SELECT and nothing else.
//                  It is the one that belongs in a web page.
//    service_role  Full write and delete access. The scraper uses it, from .env.
//                  Never put it here. The dashboard checks, and refuses to run
//                  if it finds one.
//
//  After you change this file, reload the dashboard in your browser.
// ============================================================================

window.DASHBOARD_CONFIG = {
  // Looks like https://abcdefghijklmnop.supabase.co
  supabaseUrl: "PASTE_YOUR_PROJECT_URL_HERE",

  // The long "anon" key. It starts with "eyJ".
  supabaseAnonKey: "PASTE_YOUR_ANON_KEY_HERE",

  // The name at the top of the dashboard. Leave it as "" to use the name of
  // the own_store dealer from config/dealers.yml.
  dealershipName: "",
};
