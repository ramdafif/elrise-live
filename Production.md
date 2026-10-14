# ELRISE HRIS - Kesiapan Demo, MVP, dan Production

Tanggal audit: **14 Oktober 2026**, timezone Asia/Jakarta.

Dokumen ini berdasarkan source code, konfigurasi lokal yang dibaca tanpa membuka secret/password, pengujian terakhir pada 13 Oktober 2026, dan laporan QA browser yang tersedia. Audit ini tidak melakukan deployment atau menjalankan ulang suite aplikasi. Tidak ada perubahan database maupun aplikasi Gajiku.

## 1. Jawaban singkat

- **Demo lokal/presentasi: sudah cukup.** Ketiga role dan alur utama terhubung ke database nyata, bukan hanya halaman visual.
- **MVP fungsional: sudah ada.** Superadmin membuat tenant/Admin PT, Admin PT mengelola kantor dan karyawan, Employee melakukan absensi tervalidasi, lalu Admin melihat foto/GPS dan mengekspor laporan.
- **Demo absensi pada HP fisik: perlu persiapan dan verifikasi tambahan.** Gunakan staging HTTPS, koordinat kantor yang benar, serta uji kamera/GPS perangkat asli. QA browser sebelumnya menggunakan sensor simulasi.
- **Production untuk data karyawan nyata: belum dinyatakan siap.** Selesaikan P0 dan kriteria penerimaannya terlebih dahulu. Tes lokal yang lulus tidak membuktikan deployment, hardware, recovery, atau kepatuhan hukum.

Penutupan gap deployment, keamanan operasional, privasi, dan UAT tetap wajib sebelum production. Pengembangan payroll, koreksi absensi, dan management fitur sekarang mengikuti `Planning.md`, di lingkungan terpisah agar demo presentasi tetap stabil.

Pembaruan pengembangan 14 Oktober 2026: tahap 1 management fitur dan tahap 2 koreksi absensi dengan approval/audit selesai di development/QA; 136 tes pytest serta smoke test Edge desktop/mobile lulus. Ini bukan deployment/sign-off production. Database demo existing tidak dimigrasi, Gajiku Live tidak diubah, dan payroll belum dibangun. Rincian lingkungan, migrasi, bukti backup/restore SQL development, serta batasan akses folder foto lama tersedia di `README.md` dan `Planning.md`.

Gap tambahan tahap 2: kebijakan retensi/penghapusan audit koreksi belum disepakati. Koreksi, audit, dan absensi terkait sengaja dipertahankan; perintah penghapusan karyawan ditolak bila ada audit koreksi. Retensi foto tetap berlaku. Tetapkan kewajiban retensi dan prosedur penghapusan/backup sebelum memakai data production. Jadwal tanpa absensi asli memakai snapshot kantor saat pengajuan, bukan histori penempatan; HR harus memverifikasinya. Kamera/GPS tetap perlu UAT perangkat nyata.

## 2. Fitur MVP yang sudah tersedia

### Superadmin

- Login/dashboard: jumlah perusahaan/karyawan dan ringkasan kehadiran.
- Tambah/edit PT, aktif/nonaktif, batas karyawan, masa layanan, dan status subscription sederhana.
- Membuat Admin PT dan reset password yang mencabut sesi lama.

### Admin PT

- Dashboard dan profil perusahaan milik tenant sendiri.
- Tambah, lihat/cari, edit, nonaktifkan, dan hapus karyawan dengan batasan riwayat; akun Employee dibuat bersama data karyawan.
- CRUD kantor, koordinat, radius, batas akurasi GPS, jam kerja, dan hari kerja.
- Import .xlsx secara atomik, template import, serta reset password Employee.
- Laporan dengan filter, pencarian/pagination, status kehadiran, foto privat, informasi GPS, dan export .xlsx.
- Persetujuan/penolakan izin dan cuti.

### Employee

- Login, dashboard pribadi, profil pekerjaan, dan ganti password.
- Pemberitahuan privasi, persetujuan ber-versi, dan penarikan persetujuan.
- Check-in/check-out dengan kamera, GPS, validasi server, selfie privat, dan riwayat sendiri.
- Pengajuan izin/cuti/sakit, melihat keputusan, dan cancel pengajuan pending.
- Tampilan mobile-first dengan bottom navigation; desktop login diuji tanpa scroll pada delapan ukuran viewport.

### Batasan istilah CRUD

- **PT:** create/read/update dan aktif/nonaktif; tidak ada hapus tenant permanen, yang memang tidak dijanjikan v1.
- **Karyawan:** CRUD tersedia, tetapi hapus melalui UI hanya jika belum punya riwayat. Jika sudah ada, nonaktifkan atau ikuti prosedur penghapusan terkontrol.
- **Kantor:** CRUD tersedia; kantor yang masih direferensikan tidak boleh dihapus.
- **Akun:** pengelolaan mengikuti role/relasi karyawan/PT, bukan CRUD akun bebas atau permission dinamis. Superadmin awal dibuat lewat CLI.
- **Absensi:** pencatatan, check-out, baca, dan export; belum ada edit/koreksi/hapus bebas oleh HR.
- **Izin/cuti:** pengajuan, baca, keputusan, dan cancel pending; bukan CRUD bebas keputusan final.
- **Subscription:** masa aktif/kapasitas, bukan pembayaran, invoice, atau billing otomatis.

Pembatasan hapus disengaja untuk menjaga relasi/riwayat, bukan tombol yang belum terhubung ke database.

### Proteksi dasar yang sudah diimplementasikan

- Hash password Werkzeug, session, RBAC, CSRF, pemeriksaan status akun/tenant, serta isolasi query tenant.
- Parameterized SQL, foreign key komposit, transaksi/locking, dan unique constraint absensi per tanggal kerja.
- Throttle login berbasis DB, pencabutan sesi saat reset, dan ganti password awal untuk akun yang dibuat lewat UI.
- Validasi server untuk geofence, GPS, jam perangkat, challenge, ukuran/format foto, dan input Excel.
- Foto di luar static, kontrol akses owner/Admin PT yang sesuai, security headers, cookie production, dan CLI retensi.

Ini proteksi dasar, **bukan klaim bebas celah atau sudah lulus penetration test**.

## 3. Bukti pengujian dan hal yang belum dibuktikan

Verifikasi terakhir pada **13 Oktober 2026**:

- **70 tes pytest lulus**: login tiga role, tenant/RBAC, CSRF, status akun/layanan, absensi valid/invalid, selfie, concurrency, import, cuti, export, foto privat, dan end-to-end.
- **9 pemeriksaan browser lulus** di Microsoft Edge headless: delapan ukuran desktop login, form/error tetap terlihat, modal, navigasi mobile, absensi, logo, dan download; tidak ada error JavaScript/CSP yang dilaporkan.
- Database uji nyata: **MariaDB 10.4.32 melalui mysql-connector-python**, bukan SQLite atau database mock.
- Kamera/GPS QA browser: **simulasi**, bukan perangkat HP fisik.

Bukti: `tests/test_access.py`, `tests/test_attendance.py`, `tests/test_workflows.py`, `tests/browser_smoke.py`, dan `test-results/browser-report.json`. Hasil QA diabaikan Git; simpan bukti rilis secara internal tanpa mengekspos foto/akun uji.

Belum dibuktikan: MySQL 8 target deployment, Gunicorn/Linux, HTTPS/proxy production, Android/iOS nyata, load test target tenant, backup restore, monitoring/alert, dan pemenuhan kewajiban hukum. Fixtures suite memakai APP_ENV development; konfigurasi production perlu pemeriksaan khusus.

## 4. P0 - Wajib ditutup sebelum production dengan data nyata

Semua item ini **masih terbuka atau belum terverifikasi**. Sertakan bukti saat menutup checkbox. P0 adalah keputusan kesiapan proyek, bukan pernyataan bahwa setiap kontrol merupakan kewajiban hukum yang sama untuk semua perusahaan.

### P0-01. Konfigurasi dan kredensial production

Lokal: APP_ENV=development, user DB root tanpa password, cookie Secure=false, trusted hosts localhost, database elrise_flask_dev. Jangan menyalin .env lokal ke server publik.

- [ ] Buat secret/password DB unik untuk production; jangan memakai akun/password demo.
- [ ] Set APP_ENV=production, kontak privasi nyata, domain di TRUSTED_HOSTS, cookie Secure, dan debug/testing mati.
- [ ] Gunakan user DB runtime khusus dengan hak SELECT/INSERT/UPDATE/DELETE hanya pada DB aplikasi, bukan root.
- [ ] Pisahkan kredensial provisioning/QA dari runtime; batasi akses .env, backup, dan log.
- [ ] Pastikan secret, foto, import/password, dan akun demo tidak ikut artefak rilis atau Git history; rotasi bila pernah bocor.

**Lulus jika:** konfigurasi production dan user terbatas berjalan, akun demo tidak ada, cookie/domain/secret diperiksa. Kode sudah memaksa Secure pada APP_ENV=production; perilaku melalui HTTPS tetap perlu diuji.

### P0-02. Database khusus dan target MySQL

elrise_db di workspace sudah digunakan aplikasi lain dengan schema Prisma. Jangan import, menimpa, atau menghapusnya. Distribusi menargetkan elrise_db; development Flask memakai elrise_flask_dev.

- [ ] Provision **database kosong khusus Elrise** pada instance production yang disepakati; nama elrise_db hanya bila tidak bertabrakan.
- [ ] Jalankan init-db dengan akun provisioning, lalu create-superadmin; jangan seed-demo pada production.
- [ ] Verifikasi versi MySQL target, utf8mb4, FK, CHECK constraints, index, unique constraint, dan timezone koneksi.
- [ ] Jalankan regression di **server/database QA terpisah** dengan connector yang sama; runtime production tidak diberi hak create/drop DB.
- [ ] Uji tenant -> admin -> kantor -> employee -> absensi -> export pada staging yang memakai target MySQL tersebut.

**Lulus jika:** schema, regression, dan alur staging lulus pada MySQL target tanpa menyentuh Gajiku/aplikasi existing. Guard init-db bukan sistem migrasi untuk setiap rilis berikutnya.

### P0-03. Linux, Gunicorn, HTTPS, dan proxy

Repo menyediakan entrypoint wsgi dan contoh deployment, bukan deployment production yang sudah dijalankan. Jangan gunakan Flask development server untuk production.

- [ ] Siapkan Linux/service user non-root, virtualenv bersih, dependency, pip check, dan pemeriksaan temuan keamanan dependency.
- [ ] Jalankan wsgi:app melalui Gunicorn + supervisor seperti systemd; buktikan restart/reboot memulihkan layanan.
- [ ] Pasang domain, HTTPS/renewal, reverse proxy, dan firewall; port Gunicorn/MySQL tidak boleh publik.
- [ ] Atur Host/protokol/IP dari proxy dengan benar. TRUST_PROXY_HOPS harus cocok dengan proxy tepercaya yang benar-benar ada.
- [ ] Verifikasi Secure/HttpOnly/SameSite, CSRF, CSP, allowed hosts, foto privat, dan tidak ada mixed content pada domain staging/production.
- [ ] Sinkronkan NTP dan buktikan timestamp konsisten dalam WIB.

**Lulus jika:** alur berjalan lewat HTTPS, proses pulih setelah restart, port internal tidak publik, header/IP/rate limit benar melalui proxy. Gunicorn belum diuji di Linux pada pekerjaan lokal ini.

### P0-04. Storage selfie privat dan persisten

Kode storage privat sudah ada; permission/persistensi deployment belum dibuktikan.

- [ ] Set PRIVATE_UPLOAD_DIR ke storage persisten di luar static/document root, bukan direktori sementara.
- [ ] Periksa service user dapat menulis/membaca dan user lain tidak membaca sembarangan; mode/ACL sesuai platform.
- [ ] Blokir HTTP ke instance, static/uploads, .env, backup, dan direktori project; CDN/proxy tidak menyajikan/cache selfie sebagai file publik.
- [ ] Buktikan owner/Admin PT yang tepat bisa melihat foto, sedangkan anonim, employee lain, tenant lain, dan Superadmin ditolak.
- [ ] Uji foto tetap tersedia setelah restart/deploy; pantau disk dan pastikan write failure tidak mencatat absensi sukses palsu.

**Lulus jika:** file privat dan persisten, relasi DB/file konsisten, dan static URL publik tidak membuka foto.

### P0-05. UAT kamera dan GPS fisik

- [ ] Uji Android/Chrome dan iPhone/Safari pada HTTPS dengan koordinat/radius kantor nyata, bukan seed Jakarta atau sensor fake.
- [ ] Uji izin diterima/ditolak, GPS lambat/kurang akurat, di dalam/luar/batas radius, kamera depan, ambil ulang foto, dan perpindahan halaman.
- [ ] Uji jaringan buruk, double submit, refresh setelah submit, sesi habis, GPS usang, serta jam perangkat salah.
- [ ] Buktikan absensi, foto, lokasi, akurasi, jarak, jam server, riwayat, dan laporan konsisten di DB/storage.
- [ ] Catat perangkat/browser, tanggal, hasil, masalah, dan sign-off HR.

**Lulus jika:** perangkat sasaran menjalankan alur dan kegagalan jelas tanpa data ganda atau sukses palsu.

Kamera/GPS membutuhkan secure context dan permission. localhost pada HP bukan server PC, dan HTTP IP LAN bukan pengganti HTTPS. Jangan menjanjikan anti-GPS-spoofing, foto pasti live, atau face recognition; pembatasan UI/browser tidak membuktikan keaslian data.

### P0-06. Backup, restore, dan recovery

- [ ] Jadwalkan backup database **dan** foto, enkripsi/batasi akses, tentukan retensi, dan simpan salinan di luar host aplikasi.
- [ ] Tetapkan target kehilangan data (RPO) dan waktu pemulihan (RTO) bersama bisnis, bukan mengasumsikan SLA.
- [ ] Restore ke lingkungan terpisah; buktikan relasi tenant/user/employee/attendance, login, foto privat, laporan, dan export pulih.
- [ ] Dokumentasikan backup lama dan penghapusan data agar recovery tidak menghidupkan kembali data yang seharusnya terhapus tanpa kontrol.

**Lulus jika:** restore terbukti berhasil dan operator bisa menjalankannya. File backup saja belum cukup.

### P0-07. Retensi dan rekonsiliasi

CLI purge-data dan erase-employee sudah ada; operasi/penjadwalannya pada production belum terverifikasi.

- [ ] Tetapkan retensi foto, absensi, cuti, backup, log, export, dan import; default aplikasi bukan otomatis kebijakan yang tepat.
- [ ] Jalankan purge-data dry run, validasi hasil, lalu jadwalkan --apply dengan user/environment yang benar.
- [ ] Pasang log/alert jika job gagal; buktikan file kedaluwarsa terhapus dan riwayat/akses sesuai kebijakan.
- [ ] Siapkan rekonsiliasi foto orphan setelah crash, file hilang, dan penghapusan DB/storage yang gagal; jangan menyapu direktori sembarangan.
- [ ] Buat SOP permohonan penghapusan, verifikasi tenant/employee, dasar retensi, dan konfirmasi. CLI penghapusan permanen bukan alat merapikan demo.

**Lulus jika:** job terjadwal, hasil terbukti, kegagalan termonitor, dan salinan data memiliki kebijakan konsisten.

### P0-08. Privasi dan dasar pemrosesan

Persetujuan ber-versi/pemberitahuan sudah ada; bukan bukti seluruh kewajiban UU No. 27 Tahun 2022 tentang Pelindungan Data Pribadi terpenuhi.

- [ ] Review bersama hukum/privasi: peran Elkyno/PT sebagai pengendali/prosesor, dasar pemrosesan, tujuan, minimisasi, dan kontrak yang diperlukan.
- [ ] Finalisasi pemberitahuan yang dipahami karyawan, kontak nyata, akses foto, retensi, serta konsekuensi/alternatif jika menolak atau menarik persetujuan.
- [ ] Siapkan prosedur akses, koreksi, penghapusan, pengaduan, respons insiden, dan penilaian dampak bila diperlukan.
- [ ] Pertimbangkan hosting, vendor, transfer data, dan kewajiban perusahaan; verifikasi aturan saat go-live.

**Lulus jika:** bisnis/hukum menyetujui dokumen dan proses nyata, bukan checkbox saja. Dokumen ini bukan nasihat hukum atau sertifikasi kepatuhan.

### P0-09. Audit log perubahan administratif

**Belum diimplementasikan.** Riwayat absensi bukan log perubahan pengaturan/akun oleh Admin atau Superadmin.

- [ ] Tambahkan audit trail minimal untuk PT, kapasitas/masa layanan, akun/reset, kantor/jadwal, karyawan, keputusan cuti, dan penghapusan.
- [ ] Simpan actor user_id/role, client_id relevan, action, target, timestamp server, dan ringkasan perubahan; jangan log password, token/session, atau foto mentah.
- [ ] Batasi akses/retensi; buktikan log tidak dibaca tenant lain dan perubahan sensitif dapat ditelusuri.

**Lulus jika:** jelas siapa mengubah apa, tenant mana, dan kapan. Tidak perlu event bus atau arsitektur enterprise.

### P0-10. Monitoring, release, dan persetujuan operasional

- [ ] Pantau /health, error app/DB/storage, disk, sertifikat, backup/retensi, dan service availability dengan alert ke PIC. /health saat ini mengecek DB/waktu, bukan seluruh storage/job/recovery.
- [ ] Uji lonjakan check-in/export sesuai jumlah karyawan pilot pada stack production; catat latency, error, lock timeout, resource. Belum ada bukti kapasitas/SLA untuk angka pengguna tertentu.
- [ ] Siapkan versi rilis, staging, perubahan schema, backup sebelum perubahan, serta rollback konsisten dengan DB/file; SQL ber-versi dan SOP dapat cukup, tidak perlu framework migrasi besar.
- [ ] Tentukan PIC support/incident, reset, koreksi absensi, dan fallback jika GPS/kamera/server gagal; jangan edit SQL tanpa prosedur/jejak.
- [ ] Review batasan bisnis pada bagian 5. Fitur yang dibutuhkan sejak hari pertama harus tersedia atau memiliki fallback yang disetujui.
- [ ] Acceptance test staging -> sign-off HR/operator -> pilot terbatas dengan monitoring sebelum menambah tenant.

**Lulus jika:** preflight, recovery, UAT, PIC, dan go-live memiliki bukti; P0 tidak diabaikan tanpa penilaian/keputusan risiko tertulis.

## 5. P1 - Penguatan sesuai kebutuhan client

- **MFA Admin/Superadmin:** belum ada; prioritaskan akses berprivilege. Naikkan menjadi P0 jika risiko/kebijakan client menuntutnya.
- **Koreksi absensi dengan alasan/audit:** selesai di development tahap 2 (pengajuan, review tenant, pembatalan, audit, kehadiran efektif). Belum dipromosikan ke demo; UAT dan kebijakan retensi koreksi tetap wajib sebelum production. Bukti asli tidak ditimpa.
- **Histori penempatan/jadwal/status:** belum ada ledger ber-versi. Check-in punya snapshot kantor, tetapi sebagian rekonstruksi belum hadir/libur memakai roster/jadwal saat ini. Perubahan dapat memengaruhi laporan historis; validasi sebelum keputusan resmi.
- **Shift malam/hari libur nasional:** belum didukung. V1 satu kantor per employee, satu tanggal WIB, working_days, checkout tanggal sama; checkout sebelum end_time tidak otomatis ditolak.
- **Cuti lanjut:** saldo/kuota, approval berjenjang, revisi keputusan final, dan attachment belum termasuk v1.
- **Self-service recovery/email:** reset oleh Admin/Superadmin tersedia; email reset/notifikasi otomatis belum ada dan bukan syarat CRUD MVP.
- **Dependency/CI:** pin/lock versi hasil uji, periksa dependency, automatisasi regression. Celah berisiko tinggi menjadi P0, bukan ditunda karena daftar ini P1.
- **Abuse/performance:** nilai throttling endpoint mahal, kapasitas export, batas tenant. Multi-instance/shared storage hanya jika deployment diperluas, bukan syarat demo satu server.

Jika sebuah P1 wajib bagi client, ia menjadi blocker go-live client tersebut. Hindari rebuild dengan microservices, React, atau face recognition. Payroll, koreksi absensi, dan management fitur mengikuti scope `Planning.md` di development terpisah; integrasi live Gajiku tetap di luar fase MVP saat ini.

## 6. Runbook demo

1. Gunakan data PT/karyawan fiktif pada development/staging. Demo yang publik tetap membutuhkan hardening; jangan gunakan kredensial demo yang sudah dibagikan terbuka.
2. Pastikan DB milik Elrise ini, dependency tersedia, /health berhasil. Password demo dari DEMO_PASSWORD di .env lokal; jangan salin ke dokumentasi publik.
3. Superadmin: buat PT -> Admin PT -> batas/masa layanan -> aktifkan PT.
4. Admin PT: login/ganti password awal -> profil -> kantor, koordinat/radius/jadwal -> Employee beserta akun.
5. Employee: login/ganti password awal -> privasi -> GPS/kamera -> selfie -> check-in -> GPS/selfie lagi untuk checkout -> riwayat.
6. Admin PT: laporan -> foto/GPS -> filter -> export Excel. Checkout demo tidak perlu menunggu jam pulang; end_time belum menjadi blokir checkout v1.
7. Employee ajukan cuti pada tanggal tanpa absensi -> Admin setujui/tolak -> Employee melihat keputusan. Tunjukkan tenant kedua tidak bisa membaca tenant pertama.
8. Jelaskan batasan: jika sensor simulasi, sebutkan. Jangan mematikan geofence demi demo. Untuk HP nyata, siapkan HTTPS/koordinat/perangkat dan rehearsal.

**Kesimpulan demo:** cukup untuk nilai produk dan workflow end-to-end; bukan bukti production atau jaminan anti-kecurangan.

## 7. Urutan kerja paling praktis

1. Staging Linux + MySQL target + HTTPS, dengan secret/user DB/storage terpisah.
2. Bootstrap/regression QA/staging, verifikasi header/proxy/permission/persistensi.
3. UAT HP fisik; HR memvalidasi kantor, jadwal, laporan, dan batasan v1.
4. Audit log minimum; tutup bug/security finding.
5. Backup/restore, retensi, monitoring, release/rollback, dan fallback/SOP.
6. Privasi/kontrak/PIC; tutup P0 dengan bukti.
7. Pilot kecil yang disetujui, evaluasi, baru tambah PT/karyawan.

Tidak perlu rebuild arsitektur. Contoh environment production, bootstrap, Gunicorn, reverse proxy, dan job retensi ada di `README.md` bagian Deployment production.

**Aturan menjalankan contoh:** semua placeholder diganti, init-db hanya DB kosong khusus aplikasi, provisioning dipisahkan dari runtime, seed-demo dilarang pada production, TRUST_PROXY_HOPS sesuai topologi, dan --apply hanya setelah dry run/kebijakan disetujui.

Jalankan suite hanya di QA terpisah yang boleh membuat/menghapus DB uji, bukan host/data production. browser_smoke memerlukan Playwright/Microsoft Edge yang tersedia dan tetap sensor simulasi; bukan dependency runtime. Jumlah worker contoh README bukan hasil benchmark.

## 8. Dasar audit dan referensi

Source diperiksa: `app/config.py`, `app/__init__.py`, `app/db.py`, `app/cli.py`, `app/routes/`, `app/utils/auth.py`, `app/utils/photos.py`, `app/utils/reports.py`, `database/schema.sql`, `requirements.txt`, `.env.example`, `tests/`, `README.md`.

Referensi resmi diperiksa pada 14 Oktober 2026 untuk deployment, proxy trust, secure context, dan peninjauan privasi; tidak menggantikan uji deployment/review hukum:

~~~text
Flask - Deploying to Production
https://flask.palletsprojects.com/en/stable/deploying/
Flask - Gunicorn
https://flask.palletsprojects.com/en/stable/deploying/gunicorn/
Flask - Tell Flask it is Behind a Proxy
https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/
Gunicorn - Deploy
https://gunicorn.org/deploy/
MDN - MediaDevices.getUserMedia
https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia
MDN - Geolocation API
https://developer.mozilla.org/en-US/docs/Web/API/Geolocation_API
JDIH Kementerian Keuangan - UU 27 Tahun 2022
https://jdih.kemenkeu.go.id/dok/uu-27-tahun-2022/overview
~~~

**Status akhir: siap demo dan MVP inti, belum sign-off production.** Perbarui tanggal/status saat gap ditutup dengan bukti.
