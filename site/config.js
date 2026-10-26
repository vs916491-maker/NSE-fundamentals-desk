// Connection settings: the site signs in to the same private Supabase database as
// the F&O Desk (same email and password). The publishable key is designed to be
// public; the watchlist stays private through the access rules in
// supabase/001_watchlist.sql, which only let the email below in.
window.FD_CONFIG = {
  supabaseUrl: "https://ggybblynosipnqbzedsx.supabase.co",
  supabaseAnonKey: "sb_publishable_5_59_LRgNx4q3QjFE73cLw_7ixcvAk1",
  email: "vs916491@gmail.com",
};
