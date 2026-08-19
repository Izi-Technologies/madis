package main

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/csv"
	"errors"
	"fmt"
	"html/template"
	"log"
	"net/http"
	"net/netip"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

type app struct{ dbURL, addr, sessionKey, bootstrapPassword, mafBase, mafToken string }
type principal struct {
	Username string
	Perms    map[string]bool
}
type pageData struct {
	User                                                         principal
	Notice, Error, MAFStatus, Page, PageTitle                    string
	Facilities, FacilityIPs, IVRGroups, FacilityANIs, IVRServers [][]string
	CarrierGroups, Carriers, Routes, Rewrites, SigningHops       [][]string
	Audit, Users, Roles                                          [][]string
	LiveCalls, FacilityCallSummary, CarrierCallSummary           [][]string
	RecentCarrierCalls                                           [][]string
	ReportKpis, ReportByFacility, ReportByCarrier                [][]string
	ReportByPrefix, ReportRecentCalls                            [][]string
	CDRKpis, CDRRows                                             [][]string
	BorrowedANIs                                                 [][]string
}

func main() {
	a := app{dbURL: getenv("MADIS_DB_URL", readMadisDBURL()), addr: getenv("CONTROL_ADDR", "127.0.0.1:8090"), sessionKey: os.Getenv("CONTROL_SESSION_KEY"), bootstrapPassword: os.Getenv("CONTROL_BOOTSTRAP_PASSWORD"), mafBase: getenv("MAF_BASE_URL", ""), mafToken: os.Getenv("SIP_MAF_API_TOKEN")}
	if a.dbURL == "" {
		log.Fatal("MADIS_DB_URL is required or /etc/madis/madis.env must be readable")
	}
	if a.sessionKey == "" || a.bootstrapPassword == "" {
		log.Fatal("CONTROL_SESSION_KEY and CONTROL_BOOTSTRAP_PASSWORD are required")
	}
	if err := a.migrate(); err != nil {
		log.Fatalf("migrate: %v", err)
	}
	if err := a.ensureBootstrapAdmin(); err != nil {
		log.Fatalf("bootstrap admin: %v", err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/login", a.login)
	mux.HandleFunc("/logout", a.withUser("facility:read", a.logout))
	mux.HandleFunc("/", a.withUser("facility:read", a.dashboardPage))
	mux.HandleFunc("/dashboard", a.withUser("facility:read", a.dashboardPage))
	mux.HandleFunc("/facilities", a.withUser("facility:read", a.facilitiesEndpoint))
	mux.HandleFunc("/ivrs", a.withUser("ivr:read", a.ivrsPage))
	mux.HandleFunc("/ivr-groups", a.withUser("ivr:write", a.createIVRGroup))
	mux.HandleFunc("/facility-anis", a.withUser("facility:write", a.createFacilityANI))
	mux.HandleFunc("/facility-route", a.withUser("facility:write", a.assignFacilityRoute))
	mux.HandleFunc("/facility-ips", a.withUser("facility:write", a.createFacilityIP))
	mux.HandleFunc("/ivr-servers", a.withUser("ivr:write", a.createIVRServer))
	mux.HandleFunc("/carriers", a.withUser("carrier:read", a.carriersEndpoint))
	mux.HandleFunc("/carrier-groups", a.withUser("carrier:write", a.createCarrierGroup))
	mux.HandleFunc("/routes", a.withUser("route:read", a.routesEndpoint))
	mux.HandleFunc("/rewrites", a.withUser("route:write", a.createRewrite))
	mux.HandleFunc("/identity", a.withUser("signing:read", a.identityEndpoint))
	mux.HandleFunc("/signing", a.withUser("signing:write", a.createSigningHop))
	mux.HandleFunc("/rbac", a.withUser("user:manage", a.rbacPage))
	mux.HandleFunc("/users", a.withUser("user:manage", a.createUser))
	mux.HandleFunc("/audit", a.withUser("audit:read", a.auditPage))
	mux.HandleFunc("/reports", a.withUser("report:read", a.reportsPage))
	mux.HandleFunc("/cdrs", a.withUser("report:read", a.cdrsPage))
	mux.HandleFunc("/cdrs.csv", a.withUser("report:read", a.cdrsCSV))
	mux.HandleFunc("/testing", a.withUser("testing:read", a.testingPage))
	mux.HandleFunc("/borrow-ani", a.withUser("testing:borrow", a.borrowANI))
	mux.HandleFunc("/return-ani", a.withUser("testing:borrow", a.returnANI))
	log.Printf("Madis control UI listening on %s", a.addr)
	log.Fatal(http.ListenAndServe(a.addr, mux))
}

func getenv(k, fallback string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return fallback
}
func readMadisDBURL() string {
	b, err := os.ReadFile("/etc/madis/madis.env")
	if err != nil {
		return ""
	}
	for _, l := range strings.Split(string(b), "\n") {
		l = strings.TrimSpace(l)
		if strings.HasPrefix(l, "SIP_DB_URL=") {
			return strings.TrimPrefix(l, "SIP_DB_URL=")
		}
	}
	return ""
}
func (a app) migrate() error {
	p := getenv("CONTROL_SCHEMA_FILE", "/opt/madis-control/schema.sql")
	b, err := os.ReadFile(p)
	if err != nil {
		b, err = os.ReadFile("schema.sql")
		if err != nil {
			return err
		}
	}
	return a.execSQL(string(b))
}
func (a app) psql(stdin string, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "psql", append([]string{a.dbURL, "-X", "-v", "ON_ERROR_STOP=1"}, args...)...)
	if stdin != "" {
		cmd.Stdin = strings.NewReader(stdin)
	}
	var out, stderr bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		msg := strings.TrimSpace(stderr.String())
		if msg == "" {
			msg = err.Error()
		}
		return out.String(), errors.New(msg)
	}
	return out.String(), nil
}
func (a app) execSQL(sql string) error { _, err := a.psql(sql, "-q", "-f", "-"); return err }
func (a app) rows(sql string) ([][]string, error) {
	out, err := a.psql("", "-At", "-F", "\t", "-c", sql)
	if err != nil {
		return nil, err
	}
	var rows [][]string
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		if strings.TrimSpace(line) != "" {
			rows = append(rows, strings.Split(line, "\t"))
		}
	}
	return rows, nil
}
func (a app) scalar(sql string) string {
	r, err := a.rows(sql)
	if err != nil || len(r) == 0 || len(r[0]) == 0 {
		return ""
	}
	return r[0][0]
}

func (a app) ensureBootstrapAdmin() error {
	count := a.scalar("SELECT COUNT(*) FROM control_users")
	if count != "0" {
		return nil
	}
	salt, hash, err := hashPassword(a.bootstrapPassword)
	if err != nil {
		return err
	}
	sql := fmt.Sprintf(`INSERT INTO control_users (username,password_hash,salt) VALUES ('admin',%s,%s);
INSERT INTO control_user_roles (user_id,role_id) SELECT u.id,r.id FROM control_users u JOIN control_roles r ON r.name='admin' WHERE u.username='admin';
INSERT INTO control_audit_events (action,entity_type,entity_name,detail) VALUES ('create','user','admin','bootstrap admin');`, q(hash), q(salt))
	return a.execSQL(sql)
}

func (a app) login(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodGet {
		loginTmpl.Execute(w, nil)
		return
	}
	if err := r.ParseForm(); err != nil {
		loginTmpl.Execute(w, map[string]string{"Error": err.Error()})
		return
	}
	u := slug(r.FormValue("username"))
	p := r.FormValue("password")
	rows, err := a.rows(fmt.Sprintf("SELECT password_hash,salt FROM control_users WHERE username=%s AND active=true", q(u)))
	if err != nil || len(rows) != 1 || !verifyPassword(p, rows[0][1], rows[0][0]) {
		loginTmpl.Execute(w, map[string]string{"Error": "invalid username or password"})
		return
	}
	http.SetCookie(w, &http.Cookie{Name: "madis_control_session", Value: a.signSession(u), Path: "/", HttpOnly: true, SameSite: http.SameSiteLaxMode, Expires: time.Now().Add(12 * time.Hour)})
	http.Redirect(w, r, "/", http.StatusSeeOther)
}
func (a app) logout(w http.ResponseWriter, r *http.Request, p principal) {
	http.SetCookie(w, &http.Cookie{Name: "madis_control_session", Value: "", Path: "/", MaxAge: -1})
	http.Redirect(w, r, "/login", http.StatusSeeOther)
}
func (a app) withUser(perm string, next func(http.ResponseWriter, *http.Request, principal)) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		p, ok := a.currentUser(r)
		if !ok {
			http.Redirect(w, r, "/login", http.StatusSeeOther)
			return
		}
		if perm != "" && !p.Perms[perm] {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		next(w, r, p)
	}
}
func (a app) currentUser(r *http.Request) (principal, bool) {
	c, err := r.Cookie("madis_control_session")
	if err != nil {
		return principal{}, false
	}
	u, ok := a.verifySession(c.Value)
	if !ok {
		return principal{}, false
	}
	rows, err := a.rows(fmt.Sprintf(`SELECT p.name FROM control_users u JOIN control_user_roles ur ON ur.user_id=u.id JOIN control_role_permissions rp ON rp.role_id=ur.role_id JOIN control_permissions p ON p.id=rp.permission_id WHERE u.username=%s AND u.active=true`, q(u)))
	if err != nil || len(rows) == 0 {
		return principal{}, false
	}
	perms := map[string]bool{}
	for _, r := range rows {
		perms[r[0]] = true
	}
	return principal{Username: u, Perms: perms}, true
}
func (a app) signSession(username string) string {
	exp := time.Now().Add(12 * time.Hour).Unix()
	body := fmt.Sprintf("%s|%d", username, exp)
	sig := mac([]byte(a.sessionKey), body)
	return base64.RawURLEncoding.EncodeToString([]byte(body + "|" + sig))
}
func (a app) verifySession(v string) (string, bool) {
	raw, err := base64.RawURLEncoding.DecodeString(v)
	if err != nil {
		return "", false
	}
	parts := strings.Split(string(raw), "|")
	if len(parts) != 3 {
		return "", false
	}
	exp, err := strconv.ParseInt(parts[1], 10, 64)
	if err != nil || time.Now().Unix() > exp {
		return "", false
	}
	body := parts[0] + "|" + parts[1]
	if subtle.ConstantTimeCompare([]byte(parts[2]), []byte(mac([]byte(a.sessionKey), body))) != 1 {
		return "", false
	}
	return parts[0], true
}
func mac(key []byte, msg string) string {
	h := hmac.New(sha256.New, key)
	h.Write([]byte(msg))
	return base64.RawURLEncoding.EncodeToString(h.Sum(nil))
}
func hashPassword(password string) (string, string, error) {
	saltBytes := make([]byte, 16)
	if _, err := rand.Read(saltBytes); err != nil {
		return "", "", err
	}
	salt := base64.RawURLEncoding.EncodeToString(saltBytes)
	return salt, derive(password, salt), nil
}
func verifyPassword(password, salt, want string) bool {
	return subtle.ConstantTimeCompare([]byte(derive(password, salt)), []byte(want)) == 1
}
func derive(password, salt string) string {
	key := []byte(password)
	s := []byte(salt)
	for i := 0; i < 120000; i++ {
		h := hmac.New(sha256.New, key)
		h.Write(s)
		key = h.Sum(nil)
	}
	return base64.RawURLEncoding.EncodeToString(key)
}

func (a app) mafStatus() string {
	if a.mafBase == "" || a.mafToken == "" {
		return "MAF not configured"
	}
	req, err := http.NewRequest(http.MethodGet, strings.TrimRight(a.mafBase, "/")+"/api/v1/maf/gateways", nil)
	if err != nil {
		return "MAF config error"
	}
	req.Header.Set("Authorization", "Bearer "+a.mafToken)
	client := http.Client{Timeout: 2 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "MAF unreachable"
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		return "MAF healthy"
	}
	return fmt.Sprintf("MAF HTTP %d", resp.StatusCode)
}

func (a app) dashboardPage(w http.ResponseWriter, r *http.Request, p principal) {
	if r.URL.Path != "/" && r.URL.Path != "/dashboard" {
		http.NotFound(w, r)
		return
	}
	a.renderPage(w, r, p, "dashboard", "Dashboard")
}
func (a app) facilitiesEndpoint(w http.ResponseWriter, r *http.Request, p principal) {
	if r.Method == http.MethodGet {
		a.renderPage(w, r, p, "facilities", "Facilities")
		return
	}
	if !p.Perms["facility:write"] {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	a.createFacility(w, r, p)
}
func (a app) ivrsPage(w http.ResponseWriter, r *http.Request, p principal) {
	a.renderPage(w, r, p, "ivrs", "Data Centers")
}
func (a app) carriersEndpoint(w http.ResponseWriter, r *http.Request, p principal) {
	if r.Method == http.MethodGet {
		a.renderPage(w, r, p, "carriers", "Carriers")
		return
	}
	if !p.Perms["carrier:write"] {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	a.createCarrier(w, r, p)
}
func (a app) routesEndpoint(w http.ResponseWriter, r *http.Request, p principal) {
	if r.Method == http.MethodGet {
		a.renderPage(w, r, p, "routing", "Routing")
		return
	}
	if !p.Perms["route:write"] {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	a.createRoute(w, r, p)
}
func (a app) identityEndpoint(w http.ResponseWriter, r *http.Request, p principal) {
	if r.Method == http.MethodGet {
		a.renderPage(w, r, p, "identity", "Identity Signing")
		return
	}
	if !p.Perms["signing:write"] {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	a.createSigningHop(w, r, p)
}
func (a app) rbacPage(w http.ResponseWriter, r *http.Request, p principal) {
	a.renderPage(w, r, p, "rbac", "RBAC")
}
func (a app) auditPage(w http.ResponseWriter, r *http.Request, p principal) {
	a.renderPage(w, r, p, "audit", "Audit")
}
func (a app) reportsPage(w http.ResponseWriter, r *http.Request, p principal) {
	a.renderPage(w, r, p, "reports", "Reports")
}
func (a app) cdrsPage(w http.ResponseWriter, r *http.Request, p principal) {
	a.renderPage(w, r, p, "cdrs", "CDRs")
}
func (a app) cdrsCSV(w http.ResponseWriter, r *http.Request, p principal) {
	rows, err := a.rows(cdrRowsSQL("1000"))
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/csv; charset=utf-8")
	w.Header().Set("Content-Disposition", "attachment; filename=smart-communications-cdrs.csv")
	cw := csv.NewWriter(w)
	_ = cw.Write([]string{"Started", "Call ID", "Facility", "Caller", "Callee", "Carrier", "Status", "SIP", "Seconds", "Source IP", "Transport", "User Agent"})
	for _, row := range rows {
		_ = cw.Write(row)
	}
	cw.Flush()
}
func (a app) testingPage(w http.ResponseWriter, r *http.Request, p principal) {
	a.renderPage(w, r, p, "testing", "Testing")
}
func (a app) renderPage(w http.ResponseWriter, r *http.Request, p principal, page string, title string) {
	data, err := a.loadPage(p, page)
	if err != nil {
		data.Error = err.Error()
	}
	data.Page = page
	data.PageTitle = title
	data.Notice = r.URL.Query().Get("ok")
	data.Error = first(data.Error, r.URL.Query().Get("err"))
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	pageTmpl.Execute(w, data)
}
func (a app) loadPage(p principal, page string) (pageData, error) {
	d := pageData{User: p}
	if page == "dashboard" {
		d.MAFStatus = a.mafStatus()
	}
	qs := []struct {
		name string
		dst  *[][]string
		sql  string
	}{}
	add := func(name string, dst *[][]string, sql string) {
		qs = append(qs, struct {
			name string
			dst  *[][]string
			sql  string
		}{name, dst, sql})
	}
	switch page {
	case "dashboard":
		add("live_calls", &d.LiveCalls, "SELECT m.call_id, m.state, COALESCE(m.from_uri,''), COALESCE(m.to_uri,''), COALESCE(m.application_data->>'source_ip',''), COALESCE(f.name,'Unassigned'), to_char(m.created_at,'HH24:MI:SS'), COALESCE(m.application_data->>'transport','') FROM maf_calls m LEFT JOIN control_facility_anis a ON CASE WHEN a.match_type='range' THEN NULLIF(regexp_replace(COALESCE(m.from_uri,''),'[^0-9]','','g'),'')::numeric BETWEEN NULLIF(regexp_replace(a.range_start,'[^0-9]','','g'),'')::numeric AND NULLIF(regexp_replace(a.range_end,'[^0-9]','','g'),'')::numeric WHEN a.match_type='prefix' THEN regexp_replace(COALESCE(m.from_uri,''),'[^0-9+]','','g') LIKE '%' || regexp_replace(a.ani,'[^0-9+]','','g') || '%' ELSE regexp_replace(COALESCE(m.from_uri,''),'[^0-9+]','','g') LIKE '%' || regexp_replace(a.ani,'[^0-9+]','','g') || '%' END LEFT JOIN control_facility_ips fi ON fi.ip = COALESCE(m.application_data->>'source_ip','') AND fi.enabled LEFT JOIN control_facilities f ON f.id=COALESCE(a.facility_id, fi.facility_id) WHERE m.ended_at IS NULL AND m.state NOT IN ('ended','completed','failed') ORDER BY m.updated_at DESC LIMIT 50")
		add("facility_call_summary", &d.FacilityCallSummary, "SELECT COALESCE(f.name,'Unassigned'), COUNT(*)::text FROM maf_calls m LEFT JOIN control_facility_anis a ON CASE WHEN a.match_type='range' THEN NULLIF(regexp_replace(COALESCE(m.from_uri,''),'[^0-9]','','g'),'')::numeric BETWEEN NULLIF(regexp_replace(a.range_start,'[^0-9]','','g'),'')::numeric AND NULLIF(regexp_replace(a.range_end,'[^0-9]','','g'),'')::numeric WHEN a.match_type='prefix' THEN regexp_replace(COALESCE(m.from_uri,''),'[^0-9+]','','g') LIKE '%' || regexp_replace(a.ani,'[^0-9+]','','g') || '%' ELSE regexp_replace(COALESCE(m.from_uri,''),'[^0-9+]','','g') LIKE '%' || regexp_replace(a.ani,'[^0-9+]','','g') || '%' END LEFT JOIN control_facility_ips fi ON fi.ip = COALESCE(m.application_data->>'source_ip','') AND fi.enabled LEFT JOIN control_facilities f ON f.id=COALESCE(a.facility_id, fi.facility_id) WHERE m.ended_at IS NULL AND m.state NOT IN ('ended','completed','failed') GROUP BY COALESCE(f.name,'Unassigned') ORDER BY COUNT(*) DESC, 1 LIMIT 20")
		add("carrier_call_summary", &d.CarrierCallSummary, "SELECT COALESCE(NULLIF(gateway,''),'Unknown'), COUNT(*)::text FROM cdr WHERE started_at > NOW() - INTERVAL '1 hour' GROUP BY COALESCE(NULLIF(gateway,''),'Unknown') ORDER BY COUNT(*) DESC, 1 LIMIT 20")
		add("recent_carrier_calls", &d.RecentCarrierCalls, "SELECT to_char(started_at,'HH24:MI:SS'), COALESCE(caller,''), COALESCE(callee,''), COALESCE(NULLIF(gateway,''),'Unknown'), COALESCE(status,''), COALESCE(sip_code::text,''), COALESCE(duration_sec::text,'') FROM cdr ORDER BY started_at DESC LIMIT 30")
		add("facilities", &d.Facilities, "SELECT f.id,f.name,f.code,f.enabled,COALESCE(g.name,'Unassigned') FROM control_facilities f LEFT JOIN control_ivr_groups g ON g.id=f.ivr_group_id ORDER BY f.name")
		add("ivr_servers", &d.IVRServers, "SELECT s.id,g.name,s.name,s.ip,s.port,s.transport,s.trusted,s.enabled FROM control_ivr_servers s JOIN control_ivr_groups g ON g.id=s.group_id ORDER BY g.name,s.name")
		add("carriers", &d.Carriers, "SELECT c.id,g.name,c.name,c.ip,c.port,c.transport,c.priority,c.weight,c.enabled FROM control_carriers c JOIN control_carrier_groups g ON g.id=c.group_id ORDER BY g.name,c.priority,c.name")
		add("routes", &d.Routes, "SELECT r.id,r.name,r.prefix,g.name,r.priority,r.strip_prefix,r.add_prefix,r.enabled FROM control_outbound_routes r JOIN control_carrier_groups g ON g.id=r.carrier_group_id ORDER BY r.priority,length(r.prefix) DESC,r.prefix")
	case "reports":
		add("report_kpis", &d.ReportKpis, "SELECT 'Total Calls', COUNT(*)::text FROM cdr WHERE started_at > NOW() - INTERVAL '24 hours' UNION ALL SELECT 'Completed', COUNT(*)::text FROM cdr WHERE started_at > NOW() - INTERVAL '24 hours' AND COALESCE(status,'') ILIKE ANY (ARRAY['%complete%','%answer%','%ok%']) UNION ALL SELECT 'Failed', COUNT(*)::text FROM cdr WHERE started_at > NOW() - INTERVAL '24 hours' AND COALESCE(status,'') NOT ILIKE ALL (ARRAY['%complete%','%answer%','%ok%']) AND (ended_at IS NOT NULL OR sip_code >= 300) UNION ALL SELECT 'Avg Seconds', COALESCE(ROUND(AVG(duration_sec))::text,'0') FROM cdr WHERE started_at > NOW() - INTERVAL '24 hours' AND duration_sec IS NOT NULL")
		add("report_by_facility", &d.ReportByFacility, "SELECT COALESCE(f.name,'Unassigned'), COUNT(*)::text, COALESCE(ROUND(AVG(c.duration_sec))::text,'0') FROM cdr c LEFT JOIN control_facility_anis a ON CASE WHEN a.match_type='range' THEN NULLIF(regexp_replace(COALESCE(c.caller,c.from_uri,''),'[^0-9]','','g'),'')::numeric BETWEEN NULLIF(regexp_replace(a.range_start,'[^0-9]','','g'),'')::numeric AND NULLIF(regexp_replace(a.range_end,'[^0-9]','','g'),'')::numeric WHEN a.match_type='prefix' THEN regexp_replace(COALESCE(c.caller,c.from_uri,''),'[^0-9+]','','g') LIKE '%' || regexp_replace(a.ani,'[^0-9+]','','g') || '%' ELSE regexp_replace(COALESCE(c.caller,c.from_uri,''),'[^0-9+]','','g') LIKE '%' || regexp_replace(a.ani,'[^0-9+]','','g') || '%' END LEFT JOIN control_facility_ips fi ON fi.ip = COALESCE(c.source_ip,'') AND fi.enabled LEFT JOIN control_facilities f ON f.id=COALESCE(a.facility_id, fi.facility_id) WHERE c.started_at > NOW() - INTERVAL '24 hours' GROUP BY COALESCE(f.name,'Unassigned') ORDER BY COUNT(*) DESC, 1 LIMIT 20")
		add("report_by_carrier", &d.ReportByCarrier, "SELECT COALESCE(NULLIF(gateway,''),'Unknown'), COUNT(*)::text, COALESCE(ROUND(AVG(duration_sec))::text,'0') FROM cdr WHERE started_at > NOW() - INTERVAL '24 hours' GROUP BY COALESCE(NULLIF(gateway,''),'Unknown') ORDER BY COUNT(*) DESC, 1 LIMIT 20")
		add("report_by_prefix", &d.ReportByPrefix, "SELECT CASE WHEN regexp_replace(COALESCE(callee,to_uri,destination,''),'[^0-9]','','g') LIKE '011%' THEN substring(regexp_replace(COALESCE(callee,to_uri,destination,''),'[^0-9]','','g') from 1 for 5) WHEN regexp_replace(COALESCE(callee,to_uri,destination,''),'[^0-9]','','g') LIKE '1%' THEN '1' ELSE substring(regexp_replace(COALESCE(callee,to_uri,destination,''),'[^0-9]','','g') from 1 for 3) END AS prefix, COUNT(*)::text FROM cdr WHERE started_at > NOW() - INTERVAL '24 hours' GROUP BY prefix ORDER BY COUNT(*) DESC, prefix LIMIT 20")
		add("report_recent_calls", &d.ReportRecentCalls, "SELECT to_char(started_at,'YYYY-MM-DD HH24:MI:SS'), COALESCE(caller,''), COALESCE(callee,''), COALESCE(NULLIF(gateway,''),'Unknown'), COALESCE(status,''), COALESCE(sip_code::text,''), COALESCE(duration_sec::text,''), COALESCE(source_ip,'') FROM cdr ORDER BY started_at DESC LIMIT 100")
	case "cdrs":
		add("cdr_kpis", &d.CDRKpis, "SELECT 'Total CDRs', COUNT(*)::text FROM cdr UNION ALL SELECT 'Last 24h', COUNT(*)::text FROM cdr WHERE started_at > NOW() - INTERVAL '24 hours' UNION ALL SELECT 'Answered', COUNT(*)::text FROM cdr WHERE COALESCE(status,'') ILIKE ANY (ARRAY['%complete%','%answer%','%ok%']) UNION ALL SELECT 'Failed', COUNT(*)::text FROM cdr WHERE COALESCE(status,'') NOT ILIKE ALL (ARRAY['%complete%','%answer%','%ok%']) AND (ended_at IS NOT NULL OR sip_code >= 300)")
		add("cdr_rows", &d.CDRRows, cdrRowsSQL("500"))
	case "facilities":
		add("facilities", &d.Facilities, "SELECT f.id,f.name,f.code,f.enabled,COALESCE(g.name,'Unassigned') FROM control_facilities f LEFT JOIN control_ivr_groups g ON g.id=f.ivr_group_id ORDER BY f.name")
		add("ivr_groups", &d.IVRGroups, "SELECT g.id,COALESCE(string_agg(f.name, ', ' ORDER BY f.name),'No facilities assigned'),g.name,g.dispatch_set_name,g.enabled FROM control_ivr_groups g LEFT JOIN control_facilities f ON f.ivr_group_id=g.id GROUP BY g.id,g.name,g.dispatch_set_name,g.enabled ORDER BY g.name")
		add("facility_anis", &d.FacilityANIs, "SELECT a.id,f.name,CASE WHEN a.match_type='range' THEN a.range_start || '-' || a.range_end ELSE a.ani END,a.match_type,a.enabled FROM control_facility_anis a JOIN control_facilities f ON f.id=a.facility_id ORDER BY f.name,a.range_start,a.ani LIMIT 500")
		add("facility_ips", &d.FacilityIPs, "SELECT i.id,f.name,i.ip,i.description,i.enabled FROM control_facility_ips i JOIN control_facilities f ON f.id=i.facility_id ORDER BY f.name,i.ip")
	case "ivrs":
		add("facilities", &d.Facilities, "SELECT f.id,f.name,f.code,f.enabled,COALESCE(g.name,'Unassigned') FROM control_facilities f LEFT JOIN control_ivr_groups g ON g.id=f.ivr_group_id ORDER BY f.name")
		add("ivr_groups", &d.IVRGroups, "SELECT g.id,COALESCE(string_agg(f.name, ', ' ORDER BY f.name),'No facilities assigned'),g.name,g.dispatch_set_name,g.enabled FROM control_ivr_groups g LEFT JOIN control_facilities f ON f.ivr_group_id=g.id GROUP BY g.id,g.name,g.dispatch_set_name,g.enabled ORDER BY g.name")
		add("ivr_servers", &d.IVRServers, "SELECT s.id,g.name,s.name,s.ip,s.port,s.transport,s.trusted,s.enabled FROM control_ivr_servers s JOIN control_ivr_groups g ON g.id=s.group_id ORDER BY g.name,s.name")
	case "carriers":
		add("carrier_groups", &d.CarrierGroups, "SELECT id,name,dispatch_set_name,strategy,enabled FROM control_carrier_groups ORDER BY name")
		add("carriers", &d.Carriers, "SELECT c.id,g.name,c.name,c.ip,c.port,c.transport,c.priority,c.weight,c.enabled FROM control_carriers c JOIN control_carrier_groups g ON g.id=c.group_id ORDER BY g.name,c.priority,c.name")
	case "routing":
		add("carrier_groups", &d.CarrierGroups, "SELECT id,name,dispatch_set_name,strategy,enabled FROM control_carrier_groups ORDER BY name")
		add("routes", &d.Routes, "SELECT r.id,r.name,r.prefix,g.name,r.priority,r.strip_prefix,r.add_prefix,r.enabled FROM control_outbound_routes r JOIN control_carrier_groups g ON g.id=r.carrier_group_id ORDER BY r.priority,length(r.prefix) DESC,r.prefix")
		add("rewrites", &d.Rewrites, "SELECT id,name,match_prefix,strip_digits,add_prefix,priority,enabled FROM control_number_rewrites ORDER BY priority,match_prefix")
	case "identity":
		add("signing", &d.SigningHops, "SELECT id,name,host,port,transport,priority,enabled FROM control_signing_hops ORDER BY priority,name")
	case "rbac":
		add("users", &d.Users, "SELECT u.id,u.username,string_agg(r.name,',' ORDER BY r.name),u.active FROM control_users u LEFT JOIN control_user_roles ur ON ur.user_id=u.id LEFT JOIN control_roles r ON r.id=ur.role_id GROUP BY u.id,u.username,u.active ORDER BY u.username")
		add("roles", &d.Roles, "SELECT id,name,description FROM control_roles ORDER BY name")
	case "testing":
		add("facilities", &d.Facilities, "SELECT f.id,f.name,f.code,f.enabled,COALESCE(g.name,'Unassigned') FROM control_facilities f LEFT JOIN control_ivr_groups g ON g.id=f.ivr_group_id ORDER BY f.name")
		add("facility_anis", &d.FacilityANIs, "SELECT a.id,f.name,CASE WHEN a.match_type='range' THEN a.range_start || '-' || a.range_end ELSE a.ani END,a.match_type,a.enabled FROM control_facility_anis a JOIN control_facilities f ON f.id=a.facility_id ORDER BY f.name,a.range_start,a.ani LIMIT 500")
		add("facility_ips", &d.FacilityIPs, "SELECT i.id,f.name,i.ip,i.description,i.enabled FROM control_facility_ips i JOIN control_facilities f ON f.id=i.facility_id ORDER BY f.name,i.ip")
		add("borrowed_anis", &d.BorrowedANIs, "SELECT b.id::text,f.name,b.ani,b.borrowed_by,b.purpose,to_char(b.expires_at,'YYYY-MM-DD HH24:MI'),CASE WHEN b.active THEN 'Borrowed' WHEN b.returned_at IS NOT NULL THEN 'Returned' ELSE 'Expired' END FROM control_borrowed_anis b JOIN control_facilities f ON f.id=b.facility_id ORDER BY b.active DESC,b.expires_at DESC,b.created_at DESC LIMIT 200")
	case "audit":
		add("audit", &d.Audit, "SELECT to_char(created_at,'YYYY-MM-DD HH24:MI'),action,entity_type,entity_name,detail FROM control_audit_events ORDER BY id DESC LIMIT 200")
	}
	for _, q := range qs {
		rows, err := a.rows(q.sql)
		if err != nil {
			return d, fmt.Errorf("%s: %w", q.name, err)
		}
		*q.dst = rows
	}
	return d, nil
}
func (a app) borrowANI(w http.ResponseWriter, r *http.Request, p principal) {
	if !post(w, r) {
		return
	}
	facilityID, err := positiveInt(r.FormValue("facility_id"), "facility")
	if err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	ani := digitsPlus(r.FormValue("ani"))
	purpose := clean(r.FormValue("purpose"))
	hours, err := strconv.Atoi(first(r.FormValue("hours"), "24"))
	if err != nil || hours < 1 || hours > 168 {
		redirectErr(w, r, "borrow duration must be 1-168 hours")
		return
	}
	if ani == "" || purpose == "" {
		redirectErr(w, r, "facility, ANI, and purpose are required")
		return
	}
	if err := a.execSQL("UPDATE control_borrowed_anis SET active=false WHERE active=true AND expires_at <= NOW();"); err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	matchSQL := fmt.Sprintf("SELECT COUNT(*) FROM control_facility_anis WHERE facility_id=%d AND CASE WHEN match_type='range' THEN %s::numeric BETWEEN NULLIF(regexp_replace(range_start,'[^0-9]','','g'),'')::numeric AND NULLIF(regexp_replace(range_end,'[^0-9]','','g'),'')::numeric WHEN match_type='prefix' THEN %s LIKE regexp_replace(ani,'[^0-9+]','','g') || '%%' ELSE regexp_replace(ani,'[^0-9+]','','g')=%s END", facilityID, q(ani), q(ani), q(ani))
	if a.scalar(matchSQL) == "0" {
		redirectErr(w, r, "ANI does not belong to the selected facility")
		return
	}
	activeSQL := fmt.Sprintf("SELECT COUNT(*) FROM control_borrowed_anis WHERE ani=%s AND active=true", q(ani))
	if a.scalar(activeSQL) != "0" {
		redirectErr(w, r, "ANI is already borrowed")
		return
	}
	sql := fmt.Sprintf("INSERT INTO control_borrowed_anis (facility_id,ani,borrowed_by,purpose,expires_at) VALUES (%d,%s,%s,%s,NOW() + INTERVAL '%d hours');", facilityID, q(ani), q(p.Username), q(purpose), hours)
	if err := a.execSQL(sql + audit("borrow", "ani", ani, purpose)); err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	redirectOK(w, r, "ANI borrowed for facility test")
}

func (a app) returnANI(w http.ResponseWriter, r *http.Request, p principal) {
	if !post(w, r) {
		return
	}
	loanID, err := positiveInt(r.FormValue("loan_id"), "loan")
	if err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	sql := fmt.Sprintf("UPDATE control_borrowed_anis SET returned_at=NOW(), active=false WHERE id=%d AND active=true;", loanID)
	if err := a.execSQL(sql + audit("return", "ani", strconv.Itoa(loanID), p.Username)); err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	redirectOK(w, r, "ANI returned")
}

func (a app) createUser(w http.ResponseWriter, r *http.Request, p principal) {
	if !post(w, r) {
		return
	}
	u := slug(r.FormValue("username"))
	pw := r.FormValue("password")
	roleID, err := positiveInt(r.FormValue("role_id"), "role")
	if err != nil || u == "" || len(pw) < 12 {
		redirectErr(w, r, "username, role, and a 12+ character password are required")
		return
	}
	salt, hash, err := hashPassword(pw)
	if err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	sql := fmt.Sprintf(`INSERT INTO control_users (username,password_hash,salt) VALUES (%s,%s,%s);
INSERT INTO control_user_roles (user_id,role_id) SELECT u.id,r.id FROM control_users u JOIN control_roles r ON r.id=%d WHERE u.username=%s;`, q(u), q(hash), q(salt), roleID, q(u))
	if err := a.execSQL(sql + audit("create", "user", u, "role assigned")); err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	redirectOK(w, r, "user created")
}
func (a app) createFacility(w http.ResponseWriter, r *http.Request, p principal) {
	if !post(w, r) {
		return
	}
	name := clean(r.FormValue("name"))
	code := slug(first(r.FormValue("code"), name))
	if name == "" || code == "" {
		redirectErr(w, r, "facility name is required")
		return
	}
	sql := fmt.Sprintf("INSERT INTO control_facilities (name,code) VALUES (%s,%s);", q(name), q(code))
	if err := a.execSQL(sql + audit("create", "facility", name, code)); err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	redirectOK(w, r, "facility created")
}
func (a app) assignFacilityRoute(w http.ResponseWriter, r *http.Request, p principal) {
	if !post(w, r) {
		return
	}
	facilityID, err := positiveInt(r.FormValue("facility_id"), "facility")
	if err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	groupID, err := positiveInt(r.FormValue("ivr_group_id"), "data center")
	if err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	sql := fmt.Sprintf("UPDATE control_facilities SET ivr_group_id=%d WHERE id=%d;", groupID, facilityID)
	if err := a.execSQL(sql + syncFacilityRoutesSQL() + audit("update", "facility_route", strconv.Itoa(facilityID), strconv.Itoa(groupID))); err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	redirectOK(w, r, "facility route updated")
}

func (a app) createFacilityIP(w http.ResponseWriter, r *http.Request, p principal) {
	if !post(w, r) {
		return
	}
	facilityID, err := positiveInt(r.FormValue("facility_id"), "facility")
	if err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	ip := clean(r.FormValue("ip"))
	desc := clean(r.FormValue("description"))
	if !validHost(ip) {
		redirectErr(w, r, "valid facility IP or FQDN is required")
		return
	}
	sql := fmt.Sprintf("INSERT INTO control_facility_ips (facility_id,ip,description) VALUES (%d,%s,%s);INSERT INTO access_control (source_ip,sip_user,action,skip_auth,priority,enabled,description) VALUES (%s,'*','allow',true,5,true,'facility source IP created by control UI') ON CONFLICT DO NOTHING;", facilityID, q(ip), q(desc), q(ip))
	if err := a.execSQL(sql + audit("create", "facility_ip", ip, desc)); err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	redirectOK(w, r, "facility IP added")
}

func (a app) createIVRGroup(w http.ResponseWriter, r *http.Request, p principal) {
	if !post(w, r) {
		return
	}
	name := slug(r.FormValue("name"))
	if name == "" {
		redirectErr(w, r, "data center name is required")
		return
	}
	set := "ivr_" + name
	sql := fmt.Sprintf("INSERT INTO control_ivr_groups (name,dispatch_set_name) VALUES (%s,%s);INSERT INTO dispatch_sets (name,algorithm,direction,description) VALUES (%s,'round-robin','ingress','control-ui Data Center') ON CONFLICT (name) DO UPDATE SET direction='ingress', enabled=true;", q(name), q(set), q(set))
	if err := a.execSQL(sql + audit("create", "ivr_group", name, set)); err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	redirectOK(w, r, "data center created")
}

func (a app) createFacilityANI(w http.ResponseWriter, r *http.Request, p principal) {
	if !post(w, r) {
		return
	}
	fid, err := positiveInt(r.FormValue("facility_id"), "facility")
	if err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	mt := r.FormValue("match_type")
	if mt != "prefix" && mt != "range" {
		mt = "exact"
	}
	ani := digitsPlus(r.FormValue("ani"))
	start := digitsPlus(first(r.FormValue("range_start"), ani))
	end := digitsPlus(first(r.FormValue("range_end"), ani))
	if mt == "range" {
		if start == "" || end == "" {
			redirectErr(w, r, "range start and end are required")
			return
		}
		ani = start + "-" + end
	} else if ani == "" {
		redirectErr(w, r, "ANI is required")
		return
	}
	if mt != "range" {
		start = ani
		end = ani
	}
	sql := fmt.Sprintf("INSERT INTO control_facility_anis (facility_id,ani,range_start,range_end,match_type) VALUES (%d,%s,%s,%s,%s);INSERT INTO ani_groups (name,description) SELECT 'facility:' || code, 'control-ui facility ANI group' FROM control_facilities WHERE id=%d ON CONFLICT (name) DO NOTHING;INSERT INTO ani_ranges (group_id,range_start,range_end) SELECT ag.id,%s,%s FROM ani_groups ag JOIN control_facilities f ON ag.name='facility:' || f.code WHERE f.id=%d;", fid, q(ani), q(start), q(end), q(mt), fid, q(start), q(end), fid)
	if err := a.execSQL(sql + syncFacilityRoutesSQL() + audit("create", "facility_ani", ani, mt)); err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	redirectOK(w, r, "ANI range added")
}
func (a app) createIVRServer(w http.ResponseWriter, r *http.Request, p principal) {
	if !post(w, r) {
		return
	}
	gid, err := positiveInt(r.FormValue("group_id"), "data center")
	if err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	name := slug(r.FormValue("name"))
	ip := clean(r.FormValue("ip"))
	tr := transport(r.FormValue("transport"))
	port, err := portValue(r.FormValue("port"))
	if err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	if name == "" || !validHost(ip) {
		redirectErr(w, r, "valid name and IVR IP/FQDN are required")
		return
	}
	gw := "ivr_" + name
	sql := fmt.Sprintf("INSERT INTO control_ivr_servers (group_id,name,ip,port,transport,gateway_name,trusted) VALUES (%d,%s,%s,%d,%s,%s,true);INSERT INTO gateways (name,address,port,transport,gateway_type,trusted_source,enabled) VALUES (%s,%s,%d,%s,'ivr',true,true) ON CONFLICT (name) DO UPDATE SET address=EXCLUDED.address,port=EXCLUDED.port,transport=EXCLUDED.transport,gateway_type='ivr',trusted_source=true,enabled=true;INSERT INTO dispatch_members (set_id,gateway_id,priority,weight,enabled) SELECT ds.id,gw.id,10,100,true FROM control_ivr_groups cg JOIN dispatch_sets ds ON ds.name=cg.dispatch_set_name JOIN gateways gw ON gw.name=%s WHERE cg.id=%d AND NOT EXISTS (SELECT 1 FROM dispatch_members dm WHERE dm.set_id=ds.id AND dm.gateway_id=gw.id);INSERT INTO access_control (source_ip,sip_user,action,skip_auth,priority,enabled,description) VALUES (%s,'*','allow',true,1,true,'trusted IVR created by control UI') ON CONFLICT DO NOTHING;", gid, q(name), q(ip), port, q(tr), q(gw), q(gw), q(ip), port, q(tr), q(gw), gid, q(ip))
	if err := a.execSQL(sql + audit("create", "ivr_server", name, ip)); err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	redirectOK(w, r, "trusted IVR server added")
}
func (a app) createCarrierGroup(w http.ResponseWriter, r *http.Request, p principal) {
	if !post(w, r) {
		return
	}
	name := slug(r.FormValue("name"))
	if name == "" {
		redirectErr(w, r, "carrier group name is required")
		return
	}
	set := "carrier_" + name
	sql := fmt.Sprintf("INSERT INTO control_carrier_groups (name,dispatch_set_name,strategy) VALUES (%s,%s,'priority');INSERT INTO dispatch_sets (name,algorithm,direction,description) VALUES (%s,'priority','egress','control-ui carrier group') ON CONFLICT (name) DO UPDATE SET direction='egress',enabled=true;", q(name), q(set), q(set))
	if err := a.execSQL(sql + audit("create", "carrier_group", name, set)); err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	redirectOK(w, r, "carrier group created")
}
func (a app) createCarrier(w http.ResponseWriter, r *http.Request, p principal) {
	if !post(w, r) {
		return
	}
	gid, err := positiveInt(r.FormValue("group_id"), "carrier group")
	if err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	name := slug(r.FormValue("name"))
	ip := clean(r.FormValue("ip"))
	tr := transport(r.FormValue("transport"))
	port, err := portValue(r.FormValue("port"))
	if err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	pri, _ := strconv.Atoi(first(r.FormValue("priority"), "10"))
	wt, _ := strconv.Atoi(first(r.FormValue("weight"), "100"))
	if name == "" || !validHost(ip) {
		redirectErr(w, r, "valid name and carrier IP/FQDN are required")
		return
	}
	gw := "carrier_" + name
	sql := fmt.Sprintf("INSERT INTO control_carriers (group_id,name,ip,port,transport,priority,weight,gateway_name) VALUES (%d,%s,%s,%d,%s,%d,%d,%s);INSERT INTO gateways (name,address,port,transport,gateway_type,enabled) VALUES (%s,%s,%d,%s,'carrier',true) ON CONFLICT (name) DO UPDATE SET address=EXCLUDED.address,port=EXCLUDED.port,transport=EXCLUDED.transport,gateway_type='carrier',enabled=true;INSERT INTO dispatch_members (set_id,gateway_id,priority,weight,enabled) SELECT ds.id,gw.id,%d,%d,true FROM control_carrier_groups cg JOIN dispatch_sets ds ON ds.name=cg.dispatch_set_name JOIN gateways gw ON gw.name=%s WHERE cg.id=%d AND NOT EXISTS (SELECT 1 FROM dispatch_members dm WHERE dm.set_id=ds.id AND dm.gateway_id=gw.id);", gid, q(name), q(ip), port, q(tr), pri, wt, q(gw), q(gw), q(ip), port, q(tr), pri, wt, q(gw), gid)
	if err := a.execSQL(sql + audit("create", "carrier", name, ip)); err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	redirectOK(w, r, "carrier added")
}
func (a app) createRoute(w http.ResponseWriter, r *http.Request, p principal) {
	if !post(w, r) {
		return
	}
	gid, err := positiveInt(r.FormValue("carrier_group_id"), "carrier group")
	if err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	name := slug(r.FormValue("name"))
	prefix := digitsPlus(r.FormValue("prefix"))
	strip := digitsPlus(r.FormValue("strip_prefix"))
	add := digitsPlus(r.FormValue("add_prefix"))
	pri, _ := strconv.Atoi(first(r.FormValue("priority"), "10"))
	if name == "" || prefix == "" {
		redirectErr(w, r, "route name and prefix are required")
		return
	}
	desc := fmt.Sprintf("control-ui route strip=%s add=%s", strip, add)
	sql := fmt.Sprintf("INSERT INTO control_outbound_routes (name,prefix,carrier_group_id,priority,strip_prefix,add_prefix) VALUES (%s,%s,%d,%d,%s,%s);INSERT INTO routes (prefix,dispatch_set_id,priority,description,enabled) SELECT %s,ds.id,%d,%s,true FROM control_carrier_groups cg JOIN dispatch_sets ds ON ds.name=cg.dispatch_set_name WHERE cg.id=%d;", q(name), q(prefix), gid, pri, q(strip), q(add), q(prefix), pri, q(desc), gid)
	if err := a.execSQL(sql + audit("create", "outbound_route", name, prefix)); err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	redirectOK(w, r, "outbound route created")
}
func (a app) createRewrite(w http.ResponseWriter, r *http.Request, p principal) {
	if !post(w, r) {
		return
	}
	name := slug(r.FormValue("name"))
	match := digitsPlus(r.FormValue("match_prefix"))
	add := digitsPlus(r.FormValue("add_prefix"))
	strip, _ := strconv.Atoi(first(r.FormValue("strip_digits"), "0"))
	pri, _ := strconv.Atoi(first(r.FormValue("priority"), "10"))
	if name == "" || match == "" || strip < 0 {
		redirectErr(w, r, "rewrite name, match prefix, and non-negative strip count are required")
		return
	}
	sql := fmt.Sprintf("INSERT INTO control_number_rewrites (name,match_prefix,strip_digits,add_prefix,priority) VALUES (%s,%s,%d,%s,%d);", q(name), q(match), strip, q(add), pri)
	if err := a.execSQL(sql + audit("create", "rewrite", name, match)); err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	redirectOK(w, r, "rewrite rule created")
}
func (a app) createSigningHop(w http.ResponseWriter, r *http.Request, p principal) {
	if !post(w, r) {
		return
	}
	name := slug(r.FormValue("name"))
	host := clean(r.FormValue("host"))
	tr := transport(r.FormValue("transport"))
	port, err := portValue(r.FormValue("port"))
	if err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	pri, _ := strconv.Atoi(first(r.FormValue("priority"), "10"))
	if name == "" || !validHost(host) {
		redirectErr(w, r, "valid signing-hop name and host are required")
		return
	}
	sql := fmt.Sprintf("INSERT INTO control_signing_hops (name,host,port,transport,priority) VALUES (%s,%s,%d,%s,%d);INSERT INTO gateways (name,address,port,transport,gateway_type,enabled) VALUES (%s,%s,%d,%s,'signing',true) ON CONFLICT (name) DO UPDATE SET address=EXCLUDED.address,port=EXCLUDED.port,transport=EXCLUDED.transport,gateway_type='signing',enabled=true;", q(name), q(host), port, q(tr), pri, q("signing_"+name), q(host), port, q(tr))
	if err := a.execSQL(sql + audit("create", "signing", name, host)); err != nil {
		redirectErr(w, r, err.Error())
		return
	}
	redirectOK(w, r, "signing hop added")
}
func cdrRowsSQL(limit string) string {
	return "SELECT to_char(c.started_at,'YYYY-MM-DD HH24:MI:SS'), COALESCE(c.call_id,''), COALESCE(f.name,'Unassigned'), COALESCE(c.caller,''), COALESCE(c.callee,''), COALESCE(NULLIF(c.gateway,''),'Unknown'), COALESCE(c.status,''), COALESCE(c.sip_code::text,''), COALESCE(c.duration_sec::text,''), COALESCE(c.source_ip,''), COALESCE(c.transport,''), COALESCE(c.user_agent,'') FROM cdr c LEFT JOIN control_facility_anis a ON CASE WHEN a.match_type='range' THEN NULLIF(regexp_replace(COALESCE(c.caller,c.from_uri,''),'[^0-9]','','g'),'')::numeric BETWEEN NULLIF(regexp_replace(a.range_start,'[^0-9]','','g'),'')::numeric AND NULLIF(regexp_replace(a.range_end,'[^0-9]','','g'),'')::numeric WHEN a.match_type='prefix' THEN regexp_replace(COALESCE(c.caller,c.from_uri,''),'[^0-9+]','','g') LIKE '%' || regexp_replace(a.ani,'[^0-9+]','','g') || '%' ELSE regexp_replace(COALESCE(c.caller,c.from_uri,''),'[^0-9+]','','g') LIKE '%' || regexp_replace(a.ani,'[^0-9+]','','g') || '%' END LEFT JOIN control_facility_ips fi ON fi.ip = COALESCE(c.source_ip,'') AND fi.enabled LEFT JOIN control_facilities f ON f.id=COALESCE(a.facility_id, fi.facility_id) ORDER BY c.started_at DESC LIMIT " + limit
}

func syncFacilityRoutesSQL() string {
	return "DELETE FROM routing_rules WHERE description LIKE 'control-ui facility ANI%';INSERT INTO routing_rules (match_ani_group,action,priority,description,enabled) SELECT 'facility:' || f.code,'dispatch:' || g.dispatch_set_name,10,'control-ui facility ANI to Data Center',true FROM control_facilities f JOIN control_ivr_groups g ON g.id=f.ivr_group_id WHERE f.enabled AND g.enabled;"
}
func audit(action, typ, name, detail string) string {
	return fmt.Sprintf("INSERT INTO control_audit_events (action,entity_type,entity_name,detail) VALUES (%s,%s,%s,%s);", q(action), q(typ), q(name), q(detail))
}
func post(w http.ResponseWriter, r *http.Request) bool {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return false
	}
	if err := r.ParseForm(); err != nil {
		redirectErr(w, r, err.Error())
		return false
	}
	return true
}
func redirectOK(w http.ResponseWriter, r *http.Request, msg string) {
	http.Redirect(w, r, redirectTarget(r, "ok", msg), http.StatusSeeOther)
}
func redirectErr(w http.ResponseWriter, r *http.Request, msg string) {
	http.Redirect(w, r, redirectTarget(r, "err", msg), http.StatusSeeOther)
}
func redirectTarget(r *http.Request, key string, msg string) string {
	path := "/dashboard"
	if ref := r.Header.Get("Referer"); ref != "" {
		for _, candidate := range []string{"/facilities", "/ivrs", "/carriers", "/routes", "/identity", "/testing", "/rbac", "/audit", "/reports", "/dashboard"} {
			if strings.Contains(ref, candidate) {
				path = candidate
				break
			}
		}
	}
	return path + "?" + key + "=" + urlish(msg)
}
func urlish(s string) string { return strings.ReplaceAll(strings.ReplaceAll(s, " ", "+"), "\n", "+") }
func q(s string) string      { return "'" + strings.ReplaceAll(s, "'", "''") + "'" }
func clean(s string) string  { return strings.TrimSpace(s) }
func slug(s string) string {
	s = strings.ToLower(strings.TrimSpace(s))
	var b strings.Builder
	for _, r := range s {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') || r == '_' || r == '-' {
			b.WriteRune(r)
		} else if r == ' ' || r == '.' {
			b.WriteByte('_')
		}
	}
	return strings.Trim(b.String(), "_-")
}
func digitsPlus(s string) string {
	s = strings.TrimSpace(s)
	var b strings.Builder
	for _, r := range s {
		if (r >= '0' && r <= '9') || r == '+' {
			b.WriteRune(r)
		}
	}
	return b.String()
}
func transport(s string) string {
	s = strings.ToUpper(strings.TrimSpace(s))
	switch s {
	case "TCP", "TLS", "WSS":
		return s
	default:
		return "UDP"
	}
}
func portValue(s string) (int, error) {
	if s == "" {
		return 5060, nil
	}
	p, err := strconv.Atoi(s)
	if err != nil || p < 1 || p > 65535 {
		return 0, errors.New("port must be 1-65535")
	}
	return p, nil
}
func positiveInt(s, name string) (int, error) {
	n, err := strconv.Atoi(s)
	if err != nil || n < 1 {
		return 0, fmt.Errorf("valid %s is required", name)
	}
	return n, nil
}
func validHost(s string) bool {
	if s == "" || strings.ContainsAny(s, " /@;") {
		return false
	}
	if _, err := netip.ParseAddr(s); err == nil {
		return true
	}
	for _, part := range strings.Split(s, ".") {
		if part == "" {
			return false
		}
		for _, r := range part {
			if !((r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '-') {
				return false
			}
		}
	}
	return true
}
func first(vals ...string) string {
	for _, v := range vals {
		if v != "" {
			return v
		}
	}
	return ""
}

func barWidth(v string) string {
	n, err := strconv.Atoi(v)
	if err != nil || n < 1 {
		return "3%"
	}
	w := n * 14
	if w > 100 {
		w = 100
	}
	return fmt.Sprintf("%d%%", w)
}

var loginTmpl = template.Must(template.New("login").Parse(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Madis Control</title><style>:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;color:#172033;background:#f5f7fb}*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f5f7fb}.login-shell{width:min(960px,94vw);min-height:560px;display:grid;grid-template-columns:1fr 380px;border:1px solid #d7deea;border-radius:8px;overflow:hidden;background:#fff;box-shadow:0 18px 50px rgba(20,31,54,.14)}.brand{padding:42px;background:#162033;color:#fff;display:flex;flex-direction:column;justify-content:space-between}.brand h1{font-size:40px;line-height:1;margin:0;max-width:460px}.brand p{font-size:15px;line-height:1.5;color:#cbd5e1;max-width:480px}.route-line{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.route-line span{border:1px solid rgba(255,255,255,.16);border-radius:8px;padding:12px;background:rgba(255,255,255,.05);font-size:13px;color:#dbe4f0}.login{padding:40px;align-self:center}.login h2{margin:0 0 6px;font-size:22px}.login p{margin:0 0 22px;color:#667085}.field{margin-bottom:12px}.field label{display:block;margin-bottom:6px;font-size:12px;font-weight:700;color:#475467}input,button{width:100%;font:inherit;border-radius:6px;padding:11px 12px}input{border:1px solid #ccd5e1;background:#fff}input:focus{outline:3px solid #d7e8ff;border-color:#2f6fed}button{border:1px solid #2457c5;background:#2457c5;color:#fff;font-weight:700}.err{border:1px solid #fecaca;background:#fff1f2;color:#991b1b;padding:10px;border-radius:6px;margin-bottom:14px}@media(max-width:760px){body{display:block}.login-shell{grid-template-columns:1fr;width:100%;min-height:100vh;border:0;border-radius:0}.brand{padding:26px}.brand h1{font-size:30px}.route-line{grid-template-columns:repeat(2,1fr)}.login{padding:26px}}
/* search-workflow-v1 */
.page-tools{display:flex;align-items:center;gap:12px;min-width:280px}.searchbox{position:relative;width:min(360px,32vw)}.searchbox input{width:100%;height:40px;border:1px solid #d7e0ee;border-radius:8px;background:#fff;padding:0 14px 0 36px;color:#172033;box-shadow:0 8px 20px rgba(20,33,61,.05)}.searchbox:before{content:'⌕';position:absolute;left:13px;top:8px;color:#68778c;font-size:18px;line-height:1}.searchbox input:focus{outline:none;border-color:#2f5ee8;box-shadow:0 0 0 3px rgba(47,94,232,.12)}.search-empty{display:none;margin:12px 0 0;border:1px dashed #cbd6e6;border-radius:8px;background:#fbfcfe;padding:14px;color:#68778c;text-align:center}.is-hidden{display:none!important}@media(max-width:800px){.page-head{align-items:stretch}.page-tools,.searchbox{width:100%;min-width:0}.searchbox{max-width:none}}
</style></head><body><main class="login-shell"><section class="brand"><div><h1>Madis Control</h1><p>Facility-aware SIP routing for Data Centers, trusted IVRs, and carrier egress.</p></div><div class="route-line"><span>Facilities</span><span>Data Centers</span><span>Identity</span><span>Carriers</span></div></section><form class="login" method="post"><h2>Sign in</h2><p>Operator console</p>{{with .Error}}<div class="err">{{.}}</div>{{end}}<div class="field"><label for="username">Username</label><input id="username" name="username" autocomplete="username" autofocus></div><div class="field"><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password"></div><button>Sign in</button></form></main><script>
/* search-script-v1 */
(function(){
  var input = document.getElementById('pageSearch');
  if(!input) return;
  var main = document.querySelector('main');
  function items(){
    return Array.prototype.slice.call(main.querySelectorAll('.panel table tr:not(:first-child), .facility-card, .dc-item, .report-card, .ivr-row'))
      .filter(function(el){ return !el.closest('.action-card'); });
  }
  function ensureEmpty(){
    var empty = document.getElementById('searchEmpty');
    if(empty) return empty;
    empty = document.createElement('div');
    empty.id = 'searchEmpty';
    empty.className = 'search-empty';
    empty.textContent = 'No matches found.';
    main.appendChild(empty);
    return empty;
  }
  function apply(){
    var q = input.value.trim().toLowerCase();
    var visible = 0;
    items().forEach(function(el){
      var hit = !q || el.textContent.toLowerCase().indexOf(q) !== -1;
      el.classList.toggle('is-hidden', !hit);
      if(hit) visible++;
      if(q && hit && el.tagName === 'DETAILS') el.open = true;
    });
    ensureEmpty().style.display = q && visible === 0 ? 'block' : 'none';
  }
  input.addEventListener('input', apply);
})();
</script></body></html>`))

var pageTmpl = template.Must(template.New("page").Funcs(template.FuncMap{
	"has": func(p principal, perm string) bool { return p.Perms[perm] },
	"bar": barWidth,
}).Parse(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Madis Control</title><script src="https://unpkg.com/htmx.org@2.0.4"></script><style>
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;color:#172033;background:#f5f7fb;--line:#d9e0ea;--muted:#667085;--soft:#f8fafc;--blue:#2457c5;--green:#0f7b55;--amber:#a15c00;--ink:#172033}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f5f7fb}.appbar{height:58px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 22px;position:sticky;top:0;z-index:10}.brand{display:flex;align-items:center;gap:12px}.mark{width:32px;height:32px;border-radius:7px;background:#172033;color:#fff;display:grid;place-items:center;font-weight:800}.brand h1{font-size:16px;margin:0}.brand span{display:block;font-size:12px;color:var(--muted);margin-top:1px}.nav{display:flex;gap:2px;align-items:center}.nav a{color:#344054;text-decoration:none;font-size:13px;padding:8px 10px;border-radius:6px}.nav a:hover,.nav a.active{background:#eef2f7;color:#172033}.user{display:flex;align-items:center;gap:10px;font-size:13px;color:var(--muted)}.user a{color:#2457c5;text-decoration:none}.wrap{max-width:1480px;margin:0 auto;padding:20px 22px 42px}.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin:4px 0 16px}.page-head h2{font-size:26px;line-height:1;margin:0}.page-head p{margin:7px 0 0;color:var(--muted);font-size:14px}.notice{border-radius:7px;padding:10px 12px;margin-bottom:14px;font-size:14px}.ok{border:1px solid #a7f3d0;background:#ecfdf5;color:#065f46}.err{border:1px solid #fecaca;background:#fff1f2;color:#991b1b}.dashboard{display:grid;grid-template-columns:310px minmax(0,1fr);gap:14px}.status-panel,.panel,.action-card,.report-card{background:#fff;border:1px solid var(--line);border-radius:8px}.status-panel{padding:16px}.status-line{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.status-line h2{font-size:17px;margin:0}.health{display:inline-flex;align-items:center;gap:7px;font-size:12px;color:#067647;background:#ecfdf5;border:1px solid #a7f3d0;padding:4px 8px;border-radius:999px}.health:before{content:"";width:7px;height:7px;border-radius:999px;background:#12b76a}.kpis,.report-head{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.status-panel .kpis{grid-template-columns:1fr 1fr}.kpi,.report-card{border:1px solid #edf0f5;border-radius:7px;padding:12px;background:#fbfcfe}.kpi b,.report-card b{display:block;font-size:24px;line-height:1;color:#172033}.kpi span,.report-card span{display:block;margin-top:5px;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}.route-strip{margin-top:12px;display:grid;gap:7px}.route-strip div{display:flex;align-items:center;justify-content:space-between;border:1px solid #edf0f5;border-radius:7px;padding:9px 10px;font-size:13px}.route-strip span{color:var(--muted)}.panel{overflow:hidden}.panel-head{height:46px;display:flex;align-items:center;justify-content:space-between;padding:0 14px;border-bottom:1px solid var(--line);background:#fbfcfe}.panel-head h3{font-size:14px;margin:0}.panel-head span{font-size:12px;color:var(--muted)}.panel-body{padding:12px 14px}.grid2,.report-layout,.page-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}.full{grid-column:1/-1}.action-card{padding:14px}.action-card h3{margin:0 0 12px;font-size:14px}.form{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.field label{display:block;font-size:11px;font-weight:800;color:#475467;margin-bottom:5px;text-transform:uppercase;letter-spacing:.03em}input,select,button{font:inherit;border-radius:6px;padding:8px 9px;min-width:0}input,select{border:1px solid #ccd5e1;background:#fff}input:focus,select:focus{outline:3px solid #d7e8ff;border-color:#2f6fed}button{border:1px solid var(--blue);background:var(--blue);color:#fff;font-weight:800;cursor:pointer}.span2{grid-column:span 2}.span3{grid-column:span 3}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:12.5px}th,td{text-align:left;border-bottom:1px solid #edf0f5;padding:8px 7px;vertical-align:middle;white-space:nowrap}th{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:#667085;background:#fff;font-weight:800}tr:last-child td{border-bottom:0}.empty{padding:20px;text-align:center;color:var(--muted);background:#fbfcfe}.badge{display:inline-flex;align-items:center;border-radius:999px;padding:2px 7px;font-size:12px;border:1px solid #cbd5e1;background:#f8fafc}.green{color:#067647;background:#ecfdf5;border-color:#a7f3d0}.amber{color:#92400e;background:#fffbeb;border-color:#fde68a}.code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#f1f5f9;border-radius:4px;padding:2px 5px}.chart{display:grid;gap:10px}.barrow{display:grid;grid-template-columns:minmax(120px,.45fr) minmax(160px,1fr) 40px;gap:10px;align-items:center;font-size:13px}.bartrack{height:10px;background:#edf2f7;border-radius:999px;overflow:hidden}.barfill{height:100%;background:#2457c5;border-radius:999px}.amberfill{background:#d97706}.sparkline{height:54px;display:flex;align-items:flex-end;gap:4px;margin-top:14px;padding-top:8px;border-top:1px solid #edf0f5}.sparkline span{flex:1;min-width:6px;border-radius:4px 4px 0 0;background:#c7d7fe}.sparkline span:nth-child(2n){background:#9cc2ff}.sparkline span:nth-child(3n){background:#98e0c0}.audit td{white-space:normal}@media(max-width:1080px){.dashboard,.grid2,.report-layout,.page-grid{grid-template-columns:1fr}.nav{display:none}.form{grid-template-columns:1fr}.span2,.span3{grid-column:auto}.report-head{grid-template-columns:repeat(2,1fr)}}@media(max-width:640px){.appbar{height:auto;align-items:flex-start;padding:12px;gap:10px}.user{display:block;text-align:right}.wrap{padding:14px}.kpis,.report-head{grid-template-columns:1fr}th,td{white-space:normal}.page-head{display:block}}

/* facility-workflow-v2 */
.steps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:0 0 18px}.step{background:#fff;border:1px solid #dfe7f2;border-radius:8px;padding:12px 14px;box-shadow:0 10px 26px rgba(20,33,61,.06)}.step b{display:block;font-size:12px;color:#2f5ee8;margin-bottom:3px}.step span{display:block;font-size:13px;color:#536175;line-height:1.35}.facility-directory{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}.facility-card{background:#fff;border:1px solid #dfe7f2;border-radius:8px;padding:15px;box-shadow:0 10px 26px rgba(20,33,61,.06)}.facility-card .row-top{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.facility-card h4{margin:0;font-size:15px;color:#14213d}.tagline{margin:5px 0 0;color:#536175;font-size:13px;line-height:1.35}.pill{display:inline-flex;align-items:center;gap:6px;border-radius:999px;background:#eef4ff;color:#2750bd;font-size:12px;font-weight:700;padding:5px 9px;white-space:nowrap}.meta-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:13px}.meta-item{background:#f6f8fc;border:1px solid #e7edf5;border-radius:7px;padding:9px}.meta-item small{display:block;color:#68778c;font-size:11px;text-transform:uppercase;letter-spacing:.04em}.meta-item strong{display:block;color:#172033;font-size:13px;margin-top:3px;overflow:hidden;text-overflow:ellipsis}.empty-state{border:1px dashed #cbd6e6;border-radius:8px;background:#fbfcfe;padding:22px;color:#68778c;text-align:center}.table-wrap{overflow-x:auto}.compact-table td,.compact-table th{white-space:nowrap}@media(max-width:1080px){.steps{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:720px){.steps,.meta-grid{grid-template-columns:1fr}.facility-card .row-top{display:block}.pill{margin-top:10px}}

/* datacenter-workflow-v1 */
.dc-list{display:grid;gap:12px}.dc-item{background:#fff;border:1px solid #dfe7f2;border-radius:8px;box-shadow:0 10px 26px rgba(20,33,61,.06);overflow:hidden}.dc-item summary{list-style:none;cursor:pointer;padding:16px;display:flex;align-items:center;justify-content:space-between;gap:14px}.dc-item summary::-webkit-details-marker{display:none}.dc-item summary:after{content:'+';width:28px;height:28px;border-radius:999px;background:#eef4ff;color:#2750bd;display:grid;place-items:center;font-weight:800;flex:0 0 auto}.dc-item[open] summary:after{content:'-'}.dc-title h4{margin:0;color:#14213d;font-size:15px}.dc-title p{margin:4px 0 0;color:#68778c;font-size:13px}.dc-body{border-top:1px solid #e7edf5;padding:16px;background:#fbfcfe;display:grid;grid-template-columns:minmax(0,1fr) minmax(280px,360px);gap:16px}.dc-ivrs{display:grid;gap:8px}.ivr-row{display:flex;align-items:center;justify-content:space-between;gap:10px;background:#fff;border:1px solid #e7edf5;border-radius:7px;padding:10px 12px}.ivr-row b{display:block;font-size:13px;color:#172033}.ivr-row span{display:block;font-size:12px;color:#68778c;margin-top:2px}.inline-form{background:#fff;border:1px solid #e7edf5;border-radius:8px;padding:14px}.inline-form h5{margin:0 0 10px;font-size:13px;color:#14213d}.inline-form label{margin-bottom:9px}@media(max-width:900px){.dc-body{grid-template-columns:1fr}.dc-item summary{align-items:flex-start}}

/* search-workflow-v1 */
.page-tools{display:flex;align-items:center;gap:12px;min-width:280px}.searchbox{position:relative;width:min(360px,32vw)}.searchbox input{width:100%;height:40px;border:1px solid #d7e0ee;border-radius:8px;background:#fff;padding:0 14px 0 36px;color:#172033;box-shadow:0 8px 20px rgba(20,33,61,.05)}.searchbox:before{content:'⌕';position:absolute;left:13px;top:8px;color:#68778c;font-size:18px;line-height:1}.searchbox input:focus{outline:none;border-color:#2f5ee8;box-shadow:0 0 0 3px rgba(47,94,232,.12)}.search-empty{display:none;margin:12px 0 0;border:1px dashed #cbd6e6;border-radius:8px;background:#fbfcfe;padding:14px;color:#68778c;text-align:center}.is-hidden{display:none!important}@media(max-width:800px){.page-head{align-items:stretch}.page-tools,.searchbox{width:100%;min-width:0}.searchbox{max-width:none}}
</style></head><body><header class="appbar"><div class="brand"><div class="mark">MC</div><div><h1>Madis Control</h1><span>{{.PageTitle}}</span></div></div><nav class="nav"><a href="/dashboard">Dashboard</a><a href="/reports">Reports</a><a href="/cdrs">CDRs</a>{{if has .User "testing:read"}}<a href="/testing">Testing</a>{{end}}<a href="/facilities">Facilities</a><a href="/ivrs">Data Centers</a><a href="/carriers">Carriers</a><a href="/routes">Routing</a><a href="/identity">Identity</a>{{if has .User "user:manage"}}<a href="/rbac">RBAC</a>{{end}}<a href="/audit">Audit</a></nav><div class="user"><span>{{.User.Username}}</span><a href="/logout">Sign out</a></div></header><main class="wrap">{{if .Notice}}<div class="notice ok">{{.Notice}}</div>{{end}}{{if .Error}}<div class="notice err">{{.Error}}</div>{{end}}
<div class="page-head"><div><h2>{{.PageTitle}}</h2>{{if eq .Page "dashboard"}}<p>Live call movement by facility and carrier.</p>{{end}}{{if eq .Page "reports"}}<p>Operational reporting for volume, facilities, carriers, and destinations.</p>{{end}}{{if eq .Page "cdrs"}}<p>Search, investigate, and export call detail records.</p>{{end}}{{if eq .Page "facilities"}}<p>Create a facility, open it, then add routing, ANI ranges, and source IPs.</p>{{end}}{{if eq .Page "ivrs"}}<p>Create Data Centers, open one, then add IVRs directly to it.</p>{{end}}{{if eq .Page "carriers"}}<p>Create a carrier group, open it, then add carrier IP endpoints.</p>{{end}}{{if eq .Page "routing"}}<p>Control outbound prefix routing and dial-string normalization.</p>{{end}}{{if eq .Page "identity"}}<p>Configure signing hops used before carrier delivery.</p>{{end}}{{if eq .Page "testing"}}<p>Borrow facility ANIs for controlled test calls.</p>{{end}}{{if eq .Page "rbac"}}<p>Manage operator access.</p>{{end}}{{if eq .Page "audit"}}<p>Review control-plane changes.</p>{{end}}</div>{{if ne .Page "dashboard"}}<div class="page-tools"><label class="searchbox"><input id="pageSearch" type="search" autocomplete="off" placeholder="Search this page"></label></div>{{end}}</div>
{{if eq .Page "dashboard"}}<section id="dashboard" class="dashboard" hx-get="/dashboard" hx-trigger="every 10s" hx-select="#dashboard" hx-target="#dashboard" hx-swap="outerHTML"><aside class="status-panel"><div class="status-line"><h2>Live Network</h2><span class="health">{{.MAFStatus}}</span></div><div class="kpis"><div class="kpi"><b>{{len .LiveCalls}}</b><span>Active calls</span></div><div class="kpi"><b>{{len .FacilityCallSummary}}</b><span>Facilities live</span></div><div class="kpi"><b>{{len .CarrierCallSummary}}</b><span>Carriers 1h</span></div><div class="kpi"><b>{{len .Routes}}</b><span>Routes</span></div></div><div class="route-strip"><div><strong>Ingress</strong><span>ANI to IVR</span></div><div><strong>Egress</strong><span>IVR to carrier</span></div><div><strong>Refresh</strong><span>10 seconds</span></div></div></aside><section class="panel"><div class="panel-head"><h3>Active Calls</h3><span>facility inferred by ANI</span></div><div class="table-wrap"><table><tr><th>Call</th><th>Facility</th><th>From</th><th>To</th><th>Source</th><th>State</th><th>Start</th></tr>{{range .LiveCalls}}<tr><td><span class="code">{{index . 0}}</span></td><td>{{index . 5}}</td><td>{{index . 2}}</td><td>{{index . 3}}</td><td>{{index . 4}}</td><td><span class="badge green">{{index . 1}}</span></td><td>{{index . 6}}</td></tr>{{else}}<tr><td colspan="7" class="empty">No active calls right now.</td></tr>{{end}}</table></div></section></section><div class="grid2"><section class="panel"><div class="panel-head"><h3>Facilities Sending Calls</h3><span>now</span></div><div class="panel-body"><div class="chart">{{range .FacilityCallSummary}}<div class="barrow"><strong>{{index . 0}}</strong><div class="bartrack"><div class="barfill" style="width:{{bar (index . 1)}}"></div></div><span>{{index . 1}}</span></div>{{else}}<div class="empty">No facility traffic.</div>{{end}}</div></div></section><section class="panel"><div class="panel-head"><h3>Carrier Egress</h3><span>last hour</span></div><div class="panel-body"><div class="chart">{{range .CarrierCallSummary}}<div class="barrow"><strong>{{index . 0}}</strong><div class="bartrack"><div class="barfill amberfill" style="width:{{bar (index . 1)}}"></div></div><span>{{index . 1}}</span></div>{{else}}<div class="empty">No carrier egress yet.</div>{{end}}</div></div></section></div><section class="panel full" style="margin-top:14px"><div class="panel-head"><h3>Recent Carrier Calls</h3><span>latest records</span></div><div class="table-wrap"><table><tr><th>Time</th><th>Caller</th><th>Callee</th><th>Carrier</th><th>Status</th><th>SIP</th><th>Sec</th></tr>{{range .RecentCarrierCalls}}<tr><td>{{index . 0}}</td><td>{{index . 1}}</td><td>{{index . 2}}</td><td>{{index . 3}}</td><td>{{index . 4}}</td><td>{{index . 5}}</td><td>{{index . 6}}</td></tr>{{else}}<tr><td colspan="7" class="empty">No carrier call records yet.</td></tr>{{end}}</table></div></section>{{end}}
{{if eq .Page "reports"}}<div class="report-head">{{range .ReportKpis}}<div class="report-card"><b>{{index . 1}}</b><span>{{index . 0}}</span></div>{{else}}<div class="report-card"><b>0</b><span>No call records</span></div>{{end}}</div><div class="report-layout"><section class="panel"><div class="panel-head"><h3>Calls by Facility</h3><span>last 24 hours</span></div><div class="panel-body"><div class="chart">{{range .ReportByFacility}}<div class="barrow"><strong>{{index . 0}}</strong><div class="bartrack"><div class="barfill" style="width:{{bar (index . 1)}}"></div></div><span>{{index . 1}}</span></div>{{else}}<div class="empty">No facility call records.</div>{{end}}</div></div></section><section class="panel"><div class="panel-head"><h3>Calls by Carrier</h3><span>last 24 hours</span></div><div class="panel-body"><div class="chart">{{range .ReportByCarrier}}<div class="barrow"><strong>{{index . 0}}</strong><div class="bartrack"><div class="barfill amberfill" style="width:{{bar (index . 1)}}"></div></div><span>{{index . 1}}</span></div>{{else}}<div class="empty">No carrier call records.</div>{{end}}</div></div></section><section class="panel"><div class="panel-head"><h3>Destination Prefixes</h3><span>international visibility</span></div><div class="table-wrap"><table><tr><th>Prefix</th><th>Calls</th></tr>{{range .ReportByPrefix}}<tr><td><span class="code">{{index . 0}}</span></td><td><span class="badge green">{{index . 1}}</span></td></tr>{{else}}<tr><td colspan="2" class="empty">No destination prefix data.</td></tr>{{end}}</table></div></section><section class="panel"><div class="panel-head"><h3>Facility Averages</h3><span>duration seconds</span></div><div class="table-wrap"><table><tr><th>Facility</th><th>Calls</th><th>Avg sec</th></tr>{{range .ReportByFacility}}<tr><td>{{index . 0}}</td><td>{{index . 1}}</td><td>{{index . 2}}</td></tr>{{else}}<tr><td colspan="3" class="empty">No duration data.</td></tr>{{end}}</table></div></section><section class="panel full"><div class="panel-head"><h3>Call Detail Report</h3><span>latest 100 calls</span></div><div class="table-wrap"><table><tr><th>Started</th><th>Caller</th><th>Callee</th><th>Carrier</th><th>Status</th><th>SIP</th><th>Sec</th><th>Source</th></tr>{{range .ReportRecentCalls}}<tr><td>{{index . 0}}</td><td>{{index . 1}}</td><td>{{index . 2}}</td><td>{{index . 3}}</td><td>{{index . 4}}</td><td>{{index . 5}}</td><td>{{index . 6}}</td><td>{{index . 7}}</td></tr>{{else}}<tr><td colspan="8" class="empty">No call records yet.</td></tr>{{end}}</table></div></section></div>{{end}}
{{if eq .Page "facilities"}}
<div class="page-grid">
{{if has .User "facility:write"}}<section class="action-card full"><h3>Create Facility</h3><form method="post" action="/facilities"><label>Facility Name<input name="name" placeholder="Jackson County Jail" required></label><button>Create Facility</button></form></section>{{end}}
<section class="panel full"><div class="panel-head"><h3>Facilities</h3><span>{{len .Facilities}} configured</span></div>{{if .Facilities}}<div class="dc-list">{{range .Facilities}}{{$fac := .}}<details class="dc-item facility-item"><summary><div class="dc-title"><h4>{{index $fac 1}}</h4><p>{{index $fac 2}} · {{index $fac 3}}</p></div><span class="pill">{{index $fac 4}}</span></summary><div class="dc-body"><div><div class="panel-head"><h3>Current Details</h3><span>ANI ranges and source IPs</span></div><div class="dc-ivrs">{{range $.FacilityANIs}}{{if eq (index . 1) (index $fac 1)}}<div class="ivr-row"><div><b>{{index . 2}}</b><span>{{index . 3}} ANI match</span></div><span class="badge green">{{index . 4}}</span></div>{{end}}{{end}}{{range $.FacilityIPs}}{{if eq (index . 1) (index $fac 1)}}<div class="ivr-row"><div><b>{{index . 2}}</b><span>{{index . 3}}</span></div><span class="badge green">{{index . 4}}</span></div>{{end}}{{end}}</div></div>{{if has $.User "facility:write"}}<div class="inline-form"><h5>Configure {{index $fac 1}}</h5><form method="post" action="/facility-route"><input type="hidden" name="facility_id" value="{{index $fac 0}}"><label>Route Calls To<select name="ivr_group_id" required><option value="">Choose Data Center</option>{{range $.IVRGroups}}<option value="{{index . 0}}">{{index . 1}}</option>{{end}}</select></label><button>Save Route</button></form><form method="post" action="/facility-anis"><input type="hidden" name="facility_id" value="{{index $fac 0}}"><label>ANI Match Type<select name="match_type"><option value="range">ANI Range</option><option value="exact">Single ANI</option><option value="prefix">ANI Prefix</option></select></label><label>Single ANI / Prefix<input name="ani" placeholder="1555123"></label><div class="two"><label>Range Start<input name="range_start" placeholder="15551230000"></label><label>Range End<input name="range_end" placeholder="15551239999"></label></div><button>Add ANI</button></form><form method="post" action="/facility-ips"><input type="hidden" name="facility_id" value="{{index $fac 0}}"><label>Source IP or Hostname<input name="ip" placeholder="203.0.113.25" required></label><label>Label<input name="description" placeholder="Facility SBC"></label><button>Add Source IP</button></form></div>{{end}}</div></details>{{end}}</div>{{else}}<div class="empty-state">Create the first facility above.</div>{{end}}</section>
</div>
{{end}}
{{if eq .Page "ivrs"}}
<div class="page-grid">
{{if has .User "ivr:write"}}<section class="action-card full"><h3>Create Data Center</h3><form method="post" action="/ivr-groups"><label>Data Center Name<input name="name" placeholder="baltimore" required></label><button>Create Data Center</button></form></section>{{end}}
<section class="panel full"><div class="panel-head"><h3>Data Centers</h3><span>{{len .IVRGroups}} configured</span></div>{{if .IVRGroups}}<div class="dc-list">{{range .IVRGroups}}{{$dc := .}}<details class="dc-item"><summary><div class="dc-title"><h4>{{index $dc 2}}</h4><p>{{index $dc 1}} · {{index $dc 3}}</p></div><span class="pill">Add IVRs</span></summary><div class="dc-body"><div><div class="panel-head"><h3>IVRs</h3><span>Trusted endpoints</span></div><div class="dc-ivrs">{{range $.IVRServers}}{{if eq (index . 1) (index $dc 2)}}<div class="ivr-row"><div><b>{{index . 2}}</b><span>{{index . 3}}:{{index . 4}}/{{index . 5}}</span></div><span class="badge green">trusted</span></div>{{end}}{{end}}</div></div>{{if has $.User "ivr:write"}}<form class="inline-form" method="post" action="/ivr-servers"><h5>Add IVR to {{index $dc 2}}</h5><input type="hidden" name="group_id" value="{{index $dc 0}}"><label>Name<input name="name" placeholder="ivr-1" required></label><label>IP or Hostname<input name="ip" placeholder="10.10.1.10" required></label><div class="two"><label>Port<input name="port" value="5060" required></label><label>Transport<select name="transport"><option>UDP</option><option>TCP</option><option>TLS</option></select></label></div><button>Add IVR</button></form>{{end}}</div></details>{{end}}</div>{{else}}<div class="empty-state">Create a Data Center above, then open it to add IVRs.</div>{{end}}</section>
</div>
{{end}}
{{if eq .Page "carriers"}}
<div class="page-grid">
{{if has .User "carrier:write"}}<section class="action-card full"><h3>Create Carrier Group</h3><form method="post" action="/carrier-groups"><label>Carrier Group Name<input name="name" placeholder="intl_primary" required></label><button>Create Carrier Group</button></form></section>{{end}}
<section class="panel full"><div class="panel-head"><h3>Carrier Groups</h3><span>{{len .CarrierGroups}} configured</span></div>{{if .CarrierGroups}}<div class="dc-list">{{range .CarrierGroups}}{{$cg := .}}<details class="dc-item"><summary><div class="dc-title"><h4>{{index $cg 1}}</h4><p>{{index $cg 2}} · {{index $cg 3}}</p></div><span class="pill">Add Endpoints</span></summary><div class="dc-body"><div><div class="panel-head"><h3>Carrier Endpoints</h3><span>IP targets</span></div><div class="dc-ivrs">{{range $.Carriers}}{{if eq (index . 1) (index $cg 1)}}<div class="ivr-row"><div><b>{{index . 2}}</b><span>{{index . 3}}:{{index . 4}}/{{index . 5}}</span></div><span class="badge green">{{index . 6}}/{{index . 7}}</span></div>{{end}}{{end}}</div></div>{{if has $.User "carrier:write"}}<form class="inline-form" method="post" action="/carriers"><h5>Add Endpoint to {{index $cg 1}}</h5><input type="hidden" name="group_id" value="{{index $cg 0}}"><label>Name<input name="name" placeholder="carrier-a-1" required></label><label>IP or Hostname<input name="ip" placeholder="198.51.100.10" required></label><div class="two"><label>Port<input name="port" value="5060" required></label><label>Transport<select name="transport"><option>UDP</option><option>TCP</option><option>TLS</option></select></label></div><div class="two"><label>Priority<input name="priority" value="10"></label><label>Weight<input name="weight" value="100"></label></div><button>Add Carrier Endpoint</button></form>{{end}}</div></details>{{end}}</div>{{else}}<div class="empty-state">Create a carrier group above, then open it to add endpoints.</div>{{end}}</section>
</div>
{{end}}
{{if eq .Page "routing"}}<div class="page-grid">{{if has .User "route:write"}}<section class="action-card"><h3>Create Prefix Route</h3><form class="form" method="post" action="/routes"><div class="field"><label>Name</label><input name="name" placeholder="uk_intl_primary"></div><div class="field"><label>Prefix</label><input name="prefix" placeholder="44"></div><div class="field"><label>Carrier</label><select name="carrier_group_id">{{range .CarrierGroups}}<option value="{{index . 0}}">{{index . 1}}</option>{{end}}</select></div><div class="field"><label>Priority</label><input name="priority" value="10"></div><div class="field"><label>Strip</label><input name="strip_prefix" placeholder="011"></div><div class="field"><label>Add</label><input name="add_prefix" placeholder="prefix"></div><button class="span3">Create route</button></form></section><section class="action-card"><h3>Create Rewrite</h3><form class="form" method="post" action="/rewrites"><div class="field"><label>Name</label><input name="name" placeholder="strip_011"></div><div class="field"><label>Match</label><input name="match_prefix" value="011"></div><div class="field"><label>Strip digits</label><input name="strip_digits" value="3"></div><div class="field"><label>Add</label><input name="add_prefix" placeholder="optional"></div><div class="field"><label>Priority</label><input name="priority" value="10"></div><button>Create rewrite</button></form></section>{{end}}<section class="panel"><div class="panel-head"><h3>Outbound Routes</h3><span>{{len .Routes}} prefixes</span></div><div class="table-wrap"><table><tr><th>Name</th><th>Prefix</th><th>Group</th><th>Rewrite</th></tr>{{range .Routes}}<tr><td>{{index . 1}}</td><td><span class="code">{{index . 2}}</span></td><td>{{index . 3}}</td><td>strip <span class="code">{{index . 5}}</span> add <span class="code">{{index . 6}}</span></td></tr>{{else}}<tr><td colspan="4" class="empty">No routes.</td></tr>{{end}}</table></div></section><section class="panel"><div class="panel-head"><h3>Number Rewrites</h3><span>{{len .Rewrites}} rules</span></div><div class="table-wrap"><table><tr><th>Name</th><th>Match</th><th>Strip</th><th>Add</th><th>Priority</th></tr>{{range .Rewrites}}<tr><td>{{index . 1}}</td><td><span class="code">{{index . 2}}</span></td><td>{{index . 3}}</td><td><span class="code">{{index . 4}}</span></td><td>{{index . 5}}</td></tr>{{else}}<tr><td colspan="5" class="empty">No rewrite rules.</td></tr>{{end}}</table></div></section></div>{{end}}
{{if eq .Page "identity"}}<div class="page-grid">{{if has .User "signing:write"}}<section class="action-card full"><h3>Create Signing Hop</h3><form class="form" method="post" action="/identity"><div class="field"><label>Name</label><input name="name" placeholder="signing_primary"></div><div class="field"><label>Host</label><input name="host" placeholder="signing.example.net"></div><div class="field"><label>Port</label><input name="port" value="5060"></div><div class="field"><label>Transport</label><select name="transport"><option>UDP</option><option>TCP</option><option>TLS</option></select></div><div class="field"><label>Priority</label><input name="priority" value="10"></div><button>Create hop</button></form></section>{{end}}<section class="panel full"><div class="panel-head"><h3>Signing Hops</h3><span>{{len .SigningHops}} endpoints</span></div><div class="table-wrap"><table><tr><th>Name</th><th>Target</th><th>Priority</th><th>Status</th></tr>{{range .SigningHops}}<tr><td>{{index . 1}}</td><td><span class="code">{{index . 2}}:{{index . 3}}/{{index . 4}}</span></td><td>{{index . 5}}</td><td><span class="badge green">enabled</span></td></tr>{{else}}<tr><td colspan="4" class="empty">No signing hops.</td></tr>{{end}}</table></div></section></div>{{end}}
{{if eq .Page "rbac"}}{{if has .User "user:manage"}}<div class="page-grid"><section class="action-card"><h3>Create User</h3><form class="form" method="post" action="/users"><div class="field"><label>Username</label><input name="username" placeholder="operator1"></div><div class="field"><label>Password</label><input name="password" type="password" placeholder="12+ characters"></div><div class="field"><label>Role</label><select name="role_id">{{range .Roles}}<option value="{{index . 0}}">{{index . 1}}</option>{{end}}</select></div><button class="span3">Create user</button></form></section><section class="panel"><div class="panel-head"><h3>Users</h3><span>{{len .Users}} total</span></div><div class="table-wrap"><table><tr><th>User</th><th>Roles</th><th>Active</th></tr>{{range .Users}}<tr><td>{{index . 1}}</td><td>{{index . 2}}</td><td>{{index . 3}}</td></tr>{{else}}<tr><td colspan="3" class="empty">No users.</td></tr>{{end}}</table></div></section></div>{{end}}{{end}}
{{if eq .Page "audit"}}<section class="panel"><div class="panel-head"><h3>Audit Events</h3><span>{{len .Audit}} latest</span></div><div class="table-wrap"><table class="audit"><tr><th>Time</th><th>Action</th><th>Type</th><th>Name</th><th>Detail</th></tr>{{range .Audit}}<tr><td>{{index . 0}}</td><td><span class="badge amber">{{index . 1}}</span></td><td>{{index . 2}}</td><td>{{index . 3}}</td><td>{{index . 4}}</td></tr>{{else}}<tr><td colspan="5" class="empty">No audit events.</td></tr>{{end}}</table></div></section>{{end}}
</main><script>
/* search-script-v1 */
(function(){
  var input = document.getElementById('pageSearch');
  if(!input) return;
  var main = document.querySelector('main');
  function items(){
    return Array.prototype.slice.call(main.querySelectorAll('.panel table tr:not(:first-child), .facility-card, .dc-item, .report-card, .ivr-row'))
      .filter(function(el){ return !el.closest('.action-card'); });
  }
  function ensureEmpty(){
    var empty = document.getElementById('searchEmpty');
    if(empty) return empty;
    empty = document.createElement('div');
    empty.id = 'searchEmpty';
    empty.className = 'search-empty';
    empty.textContent = 'No matches found.';
    main.appendChild(empty);
    return empty;
  }
  function apply(){
    var q = input.value.trim().toLowerCase();
    var visible = 0;
    items().forEach(function(el){
      var hit = !q || el.textContent.toLowerCase().indexOf(q) !== -1;
      el.classList.toggle('is-hidden', !hit);
      if(hit) visible++;
      if(q && hit && el.tagName === 'DETAILS') el.open = true;
    });
    ensureEmpty().style.display = q && visible === 0 ? 'block' : 'none';
  }
  input.addEventListener('input', apply);
})();
</script></body></html>`))
