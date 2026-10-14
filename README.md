# ELRISE HRIS

HRIS independen milik Elkyno Technology: Flask + MySQL, tiga role, absensi geofence + selfie, izin/cuti, dan laporan Excel. Tidak ada payroll, integrasi Gajiku, framework frontend, atau data mock di endpoint aplikasi.

## Audit Gajiku Live dan pola yang diadaptasi

Repository referensi dibaca tanpa mengubah source, environment, atau database Gajiku. Pola yang digunakan ulang adalah app factory, app.py/wsgi.py, konfigurasi environment, koneksi database per request melalui Flask g, SQL parameterized, Blueprint, session Werkzeug, Jinja, dan CSS/JavaScript biasa.

Elrise menggunakan connector MySQL langsung dengan placeholder %s. Tidak membawa fallback SQLite, worker payroll, repository/service layer, atau secret/password fallback dari aplikasi referensi. Role dan tenant diperiksa dari database pada setiap request, bukan dipercaya dari field role/client_id milik browser atau session.

**Penting untuk workspace ini:** elrise_db sudah berisi tabel Prisma milik aplikasi existing. Database tersebut tidak dimodifikasi. Konfigurasi development lokal di .env menggunakan elrise_flask_dev, dengan database serta akun seed nyata. Schema distribusi dan .env.example tetap menggunakan elrise_db. Jangan import schema ke database existing itu tanpa backup, audit kepemilikan, dan keputusan migrasi. Perintah init-db menolak database yang mengandung tabel aplikasi lain, sebelum menjalankan DDL.

## Persyaratan

- Python 3.12+.
- MySQL 8.0.16+ / 8.4, InnoDB, utf8mb4, foreign key dan CHECK constraints aktif.
- Development dapat memakai server kompatibel MySQL. Pengujian lokal dilakukan pada MariaDB 10.4.32 melalui mysql-connector-python; MySQL 8 belum tersedia di mesin ini dan perlu smoke test pada target deployment.
- Production: Linux, Gunicorn, reverse proxy HTTPS, waktu server tersinkronisasi NTP.
- Browser modern dengan JavaScript, Geolocation, dan MediaDevices. Kamera/GPS tidak tersedia pada HTTP biasa dari IP LAN; localhost merupakan pengecualian browser.

## Instalasi lokal

Jalankan dari direktori elrise:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(48))"
~~~

Isi SECRET_KEY dengan hasil generator, MYSQL_HOST/PORT/USER/PASSWORD dengan akun database Anda, MYSQL_DATABASE=elrise_db hanya jika database tersebut kosong/khusus aplikasi ini, dan PRIVACY_CONTACT dengan kontak nyata. Secret, password, foto, dan hasil QA dikecualikan oleh .gitignore. Jangan gunakan root MySQL untuk runtime production.

Inisialisasi memakai akun provisioning yang memiliki hak CREATE. Tidak ada DROP/TRUNCATE pada init-db:

~~~powershell
.\.venv\Scripts\python.exe -m flask --app wsgi init-db
.\.venv\Scripts\python.exe -m flask --app wsgi create-superadmin
.\.venv\Scripts\python.exe app.py
~~~

Password Superadmin diminta secara tersembunyi, minimal 12 karakter. Aplikasi development tersedia pada http://127.0.0.1:5002. Flask development server bukan server production.

Alternatif import SQL pada **database kosong**:

~~~sql
SOURCE /path/to/elrise/database/schema.sql;
~~~

Schema menggunakan enam tabel inti: clients, users, employees, office_locations, attendances, leave_requests. Satu tabel tambahan login_limits menyimpan throttle bersama antar-worker Gunicorn. FK komposit mencegah penempatan kantor, akun, reviewer, dan absensi lintas tenant; unique constraint melindungi satu check-in per tanggal kerja.

## Development yang sudah disiapkan di mesin ini

.env lokal sudah dibuat dengan secret dan DEMO_PASSWORD acak, MYSQL_DATABASE=elrise_flask_dev, port 5002. Akun development:

- owner@elrise.test: Superadmin.
- admin@nusantara.test: Admin PT Nusantara Digital.
- rani@nusantara.test: Employee PT Nusantara Digital.
- admin@cakrawala.test: Admin tenant kedua untuk pemeriksaan isolasi.
- bima@cakrawala.test: Employee tenant kedua.

Password kelima akun berasal dari DEMO_PASSWORD di .env lokal, bukan password hardcoded di source. Database seed berisi PT/kantor/akun, **tanpa absensi atau selfie palsu**. Kantor seed di Jakarta adalah titik uji; atur koordinat kantor yang benar sebelum mencoba GPS perangkat fisik.

Login memakai **email**, bukan username terpisah. Ketiga role masuk lewat halaman /login yang sama dan diarahkan otomatis ke workspace sesuai role pada database. Akun demo hanya untuk development; jangan menjalankan seed-demo atau memakai kredensialnya pada production.

Untuk membuat seed pada instalasi development baru, isi DEMO_PASSWORD minimal 12 karakter dan jalankan:

~~~powershell
.\.venv\Scripts\python.exe -m flask --app wsgi seed-demo
~~~

Seed menolak APP_ENV=production dan menolak database yang sudah memiliki akun. Akun demo tidak diwajibkan mengganti password demi QA lokal; semua akun yang dibuat melalui UI dan semua reset password wajib mengganti password saat login pertama. Jangan seed production, memakai password demo di production, atau mengirim password melalui kanal publik.

## Alur operasional

### Superadmin

Masuk -> Perusahaan -> Tambah PT (dapat nonaktif) -> atur batas dan periode layanan -> simpan -> buat Admin PT melalui modal -> aktifkan PT. Edit PT mengelola informasi, kapasitas, periode subscription, dan retensi foto. Reset password admin mencabut semua sesi lamanya. Perusahaan nonaktif, belum mulai, atau berakhir tidak dapat diakses oleh akun tenant, termasuk sesi yang sudah login.

### Admin PT

Masuk -> ganti password awal -> Profil perusahaan -> Kantor & geofence -> tambah kantor, koordinat, radius, akurasi dan jadwal -> Karyawan -> tambah karyawan dan akun Employee sekaligus. Setiap employee wajib ditempatkan ke kantor aktif. Kapasitas dihitung dari karyawan aktif dan dilindungi lock transaksi ketika tambah/import/reaktivasi.

Import Excel: unduh template, isi satu sheet dengan kolom sesuai urutan, maksimal 500 baris/5 MB. office_id tersedia pada halaman Import. Tanggal YYYY-MM-DD, password minimal 12 karakter. Formula, macro, link eksternal, ZIP terlalu besar, data di luar batas baris, email/nomor duplikat, atau referensi kantor tenant lain ditolak. Import bersifat atomik; satu kesalahan membatalkan seluruh import. Tidak ada dukungan .xls legacy. Lindungi dan hapus file import berisi password sesuai kebijakan perusahaan.

Edit karyawan mengelola status aktif dan mencabut sesi. Hapus permanen melalui UI hanya boleh jika belum ada riwayat; jika sudah ada, nonaktifkan dan gunakan prosedur retensi/penghapusan terkontrol. Kantor dengan referensi karyawan/absensi juga tidak dapat dihapus.

Absensi & laporan: filter rentang tanggal, kantor, status dan karyawan -> Foto & GPS -> lihat selfie serta koordinat, akurasi, jarak, dan jam server -> Export Excel. Export mengikuti filter yang sama, tidak menyertakan path foto, dan menulis string sebagai teks untuk mencegah formula injection Excel. Rentang maksimum 93 hari / 60.000 baris; persempit filter untuk tenant besar.

Izin & cuti: tinjau pengajuan pending melalui modal, beri catatan, lalu setujui/tolak. Keputusan final pada v1; tanggal dengan absensi tidak dapat disetujui menjadi cuti. Tenant lain tidak dapat membaca atau mereview pengajuan.

### Employee

Masuk -> ganti password awal -> baca dan setujui pemberitahuan privasi -> Absensi -> Aktifkan GPS & kamera -> pastikan GPS akurat dan berada dalam geofence -> Ambil selfie -> Check-in -> ulangi GPS/selfie untuk Check-out -> Riwayat. Kamera dimatikan saat halaman disembunyikan/ditinggalkan. UI tidak menyediakan input upload foto/galeri pada absensi.

Employee dapat mengajukan izin/cuti/sakit, melihat keputusan/catatan HR, membatalkan pengajuan pending, mengubah password, membaca profil, dan menarik persetujuan dari Profil. Penarikan memblokir absensi GPS/selfie berikutnya; data terdahulu tidak langsung dihapus. HR perlu menyediakan alternatif kehadiran di luar fitur ini dan menilai permohonan hak terkait data.

## Aturan absensi dan batasannya

- Haversine divalidasi di backend. Default radius 100 m dan akurasi maksimal 50 m, dapat diatur per kantor.
- Koordinat harus finite dan dalam rentang valid; akurasi positif dan tidak melebihi aturan kantor. Di luar radius ditolak.
- Waktu resmi menggunakan server UTC+07:00, Asia/Jakarta. Selisih jam perangkat > 5 menit ditolak. Lokasi browser harus baru (maksimal 60 detik relatif terhadap jam perangkat).
- Challenge bertanda tangan, masa berlaku 120 detik, terikat user, tenant, kantor, tanggal, action, dan nonce session. Challenge dirotasi saat pengambilan selfie. Ini mengurangi replay, bukan pembuktian liveness.
- Selfie hanya JPEG valid, maksimal MAX_PHOTO_BYTES (default 1 MB), 240-2000 piksel, maksimal 4 megapiksel. Browser mengompresi ke JPEG 640px; server memverifikasi, menghapus EXIF, re-encode, dan menambah watermark waktu server serta koordinat yang dilaporkan browser.
- File disimpan privat di instance/attendance atau PRIVATE_UPLOAD_DIR, **bukan static/uploads**. Path disimpan di DB. Endpoint foto memerlukan owner atau Admin PT dari tenant yang sama; Superadmin tidak dapat melihat selfie.
- Unique constraint dan row locking melindungi check-in/check-out ganda. Check-out wajib setelah check-in dalam tanggal WIB yang sama. Checkout kedua ditolak.
- Status terlambat dihitung dari jadwal masuk kantor; menit keterlambatan dibulatkan ke atas. Check-out awal tidak diblokir secara otomatis; HR dapat memeriksa jam aktual versus jadwal.
- Koordinat, radius, akurasi, nama kantor dan jam kerja disnapshot saat check-in; check-out memakai snapshot itu agar perubahan titik kantor tidak mengubah validasi hari berjalan. Kantor nonaktif tetap memblokir absensi.
- Kehadiran disimpan nyata. Status belum hadir/izin/libur pada laporan dihitung dari roster aktif, tanggal mulai kerja, hari kerja kantor dan cuti disetujui. Untuk karyawan nonaktif, laporan mempertahankan catatan hadirnya, bukan merekonstruksi histori status aktif/penempatan yang belum dicatat v1.
- V1 mendukung shift dalam satu tanggal, satu kantor penempatan per employee, tanpa kalender libur nasional, koreksi manual, offline attendance atau jadwal historis berlapis.
- getUserMedia meminta kamera depan dan menolak kamera yang mengaku facingMode selain user; webcam desktop dapat tidak melaporkan arah. Pembatasan galeri/front-camera hanya UI. Browser tidak bisa menjamin selfie live, lokasi nyata, atau mencegah spoofing/GPS injection sepenuhnya. Watermark bukan bukti kriptografis keaslian foto/lokasi.

## Privasi dan retensi

Pemberitahuan menyimpan versi dan waktu penerimaan. Perubahan PRIVACY_VERSION memerlukan persetujuan baru sebelum absensi. Jangan mengubah materi pemberitahuan tanpa memperbarui versi. Tetapkan perusahaan/platform sebagai pengendali/pemroses sesuai keadaan dan kontrak, nilai dasar pemrosesan yang tepat, minimisasi data, hak akses/koreksi/penghapusan, transparansi, keamanan, respons insiden dan backup. Checkbox saja tidak otomatis memenuhi UU No. 27 Tahun 2022; lakukan penilaian hukum/operasional sebelum production.

Konfigurasi:

- PHOTO_RETENTION_DAYS: default 30; dapat dioverride per PT (1-365 hari).
- ATTENDANCE_RETENTION_DAYS: default 365.
- LEAVE_RETENTION_DAYS: default 365 setelah akhir pengajuan.
- PRIVACY_CONTACT: kontak platform yang benar; email HR berasal dari profil perusahaan.

Periksa dry run, kemudian jadwalkan penghapusan harian:

~~~bash
flask --app wsgi purge-data
flask --app wsgi purge-data --apply
~~~

Foto kedaluwarsa dihapus dan path dikosongkan; riwayat tetap tersedia sampai retensi absensi. Catatan/pengajuan kedaluwarsa juga dihapus. Jalankan dengan user deployment yang memiliki akses file; kegagalan penghapusan harus dimonitor. Backup, salinan export, file import dan log perlu kebijakan terpisah yang konsisten. File orphan akibat crash dan foto uji yang tidak lagi direferensikan perlu rekonsiliasi storage; job ini tidak menyapu sembarang file secara rekursif.

Untuk permohonan penghapusan yang sudah dinilai dan tidak terhalang kewajiban retensi: nonaktifkan karyawan, lalu operator menjalankan perintah berikut dengan konfirmasi interaktif. Perintah memerlukan client_id dan employee_id yang cocok dan menghapus seluruh akun/riwayat/foto karyawan nonaktif itu:

~~~bash
flask --app wsgi erase-employee --client-id 1 --employee-id 10
~~~

## Logo dan tampilan

Logo memakai aset milik Anda di static/img/: Elrise-Logo.png untuk simbol dan Elrise-NameLogo.png untuk wordmark. Elrise-FullLogo.png tetap tersedia sebagai lockup lengkap. File asli tidak dimodifikasi. Login dan sidebar menampilkan logo pada kartu terang agar warna navy/teal terbaca, sedangkan header mobile Employee menggunakan logo ringkas.

Versi web dan favicon PNG dibuat dari gambar asli dengan memangkas ruang transparan serta mengubah ukuran, bukan menggambar ulang logo. Jika logo sumber diganti, jalankan ulang:

~~~powershell
.\.venv\Scripts\python.exe scripts/prepare_branding.py
~~~

## Pengujian

Hasil verifikasi lokal pada 13 Oktober 2026: **70 tes pytest lulus** dengan database nyata MariaDB 10.4.32 melalui mysql-connector-python. QA Microsoft Edge headless juga lulus **9 pemeriksaan alur/UI**, termasuk delapan ukuran desktop untuk memastikan login tanpa scroll dan panel kiri simetris/terpusat, form/error tetap terlihat, logo asli, favicon, login ketiga role, absensi, pengajuan cuti, modal, export, dan viewport mobile. Tidak ditemukan error JavaScript/CSP. Login ketiga akun demo serta /health diverifikasi kembali melalui HTTP pada server lokal port 5002. Hasil ini bukan klaim pengujian MySQL 8, perangkat GPS/kamera fisik, atau deployment production.

Suite pytest memakai database MySQL nyata dengan nama acak elrise_test_*, menolak reuse database existing, dan menghapus hanya database uji yang dibuatnya. Tidak menggunakan SQLite atau database mock. Akun/citra sintetis hanya berada di fixtures pengujian. Koneksi mengikuti MYSQL_* dari environment/.env; akun pengujian perlu hak membuat dan menghapus database uji. Jangan gunakan user runtime production untuk menjalankan suite.

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
node --check static/js/app.js
~~~

Suite memeriksa login ketiga role, RBAC, CSRF, login throttle bersama, FK dan endpoint lintas tenant, pencabutan session, client/employee nonaktif atau layanan habis/belum mulai, geofence valid/invalid, akurasi, koordinat non-finite, selfie kosong/rusak/berlebih, waktu perangkat, GPS usang, challenge palsu/expired, check-in bersamaan, checkout tanpa check-in, validasi checkout, snapshot kantor, terlambat, consent/withdrawal, retensi, CRUD, import atomik, formula injection, kapasitas bersamaan, cuti, export dan alur Superadmin -> PT -> Admin -> kantor -> Employee -> check-in/out -> laporan.

QA browser opsional (bukan dependency runtime):

~~~powershell
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe -m tests.browser_smoke
~~~

Script menggunakan Microsoft Edge yang terinstal, server lokal/database uji terpisah, viewport desktop/390px/360px, fake browser camera dan GPS simulasi. Menguji tombol, capture canvas, submit, navigasi, modal dan download. Screenshot dan browser-report.json disimpan di test-results/ yang diabaikan Git. **Tidak membuktikan GPS/kamera perangkat fisik**, kompatibilitas semua smartphone, HTTPS production, NTP server, backup restore, atau kepatuhan hukum. Lakukan pilot pada Android/iOS dengan izin diterima/ditolak, sinyal buruk, posisi tepat di batas radius, rotasi layar, dan pergantian jaringan.

## Deployment production

Gunicorn berjalan pada Linux, bukan Windows. Siapkan schema kosong, akun DB provisioning dan akun runtime dengan privilege minimum (SELECT/INSERT/UPDATE/DELETE hanya pada elrise_db), lalu gunakan environment production:

~~~dotenv
APP_ENV=production
SECRET_KEY=<secret-acak-minimal-32-karakter>
MYSQL_DATABASE=elrise_db
MYSQL_USER=elrise
MYSQL_PASSWORD=<password-kuat>
SESSION_COOKIE_SECURE=true
TRUSTED_HOSTS=hris.perusahaan.example
TRUST_PROXY_HOPS=1
PRIVATE_UPLOAD_DIR=/srv/elrise/instance/attendance
PRIVACY_CONTACT=privacy@perusahaan.example
~~~

TRUST_PROXY_HOPS hanya 1 jika **satu proxy milik Anda** benar-benar ada di depan aplikasi. Gunicorn tidak boleh diakses langsung dari internet. Jangan percaya X-Forwarded-* dari client tak tepercaya. MYSQL_SSL_CA dapat mengaktifkan verifikasi sertifikat dan identitas server pada koneksi DB remote.

~~~bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
umask 0077
gunicorn --workers 2 --threads 2 --bind 127.0.0.1:5002 --access-logfile - wsgi:app
~~~

Reverse proxy harus menyediakan sertifikat HTTPS. Contoh location Nginx di dalam server TLS milik Anda:

~~~nginx
client_max_body_size 6m;
location ^~ /static/uploads/ { return 404; }
location ^~ /instance/ { return 404; }
location /static/ { alias /srv/elrise/static/; }
location / {
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_pass http://127.0.0.1:5002;
}
~~~

Jangan alias/serve direktori project, .env, instance, atau PRIVATE_UPLOAD_DIR sebagai static. Batasi permission filesystem/NTFS ACL sesuai service user. Cookie production selalu Secure, HttpOnly, SameSite=Lax. Header CSP, frame restriction, no-store, nosniff dan HSTS disediakan aplikasi. Hindari cache/CDN untuk halaman autentikasi, response foto, dan endpoint tenant.

Contoh cron harian (sesuaikan interpreter, path, user service, dan logging):

~~~cron
15 2 * * * cd /srv/elrise && .venv/bin/flask --app wsgi purge-data --apply >> /var/log/elrise-retention.log 2>&1
~~~

Pantau /health, error database/storage, kapasitas disk, job retensi, waktu server, TLS, percobaan login dan expiry subscription. Gunakan backup terenkripsi dan uji restore; jangan menyimpan PII/password/selfie dalam log debugging. Belum ada otomasi billing atau audit log perubahan administratif pada v1.
