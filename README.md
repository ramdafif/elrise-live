# ELRISE HRIS

HRIS independen milik Elkyno Technology: Flask + MySQL, tiga role, absensi geofence + selfie, koreksi dengan approval/audit, izin/cuti, dan laporan Excel. Modul payroll dan integrasi Gajiku belum dibangun; tidak ada framework frontend atau data mock di endpoint aplikasi.

Kesiapan demo/MVP, batasan CRUD, dan checklist sebelum production tersedia di [Production.md](Production.md). Checklist membedakan fitur yang sudah ada dari deployment, UAT perangkat fisik, dan proses operasional yang belum diverifikasi.

## Pengembangan Fitur: Tahap 1 dan 2

Management fitur per client tersedia di Superadmin > Perusahaan > Detail PT > Fitur & integrasi. Default: payroll OFF, koreksi absensi ON, Gajiku OFF. Hanya Superadmin dapat menyimpan perubahan; setiap perubahan mencatat aktor, waktu, dan nilai sebelum/sesudah. Izin Gajiku memerlukan payroll aktif dan tetap menampilkan belum dikonfigurasi, bukan koneksi live.

Tahap 1 mengimplementasikan entitlement, audit, guard backend, dan migrasi. Tahap 2 menambahkan alur koreksi end-to-end di development. Modul payroll belum tersedia. Akses fitur menggunakan guard `feature_required` yang tetap memeriksa role, tenant, masa layanan, dan konfigurasi terbaru pada setiap request; operasi koreksi memeriksa ulang akses di dalam transaksi.

### Demo stabil dan development terpisah di mesin ini

- Demo presentasi existing: `http://127.0.0.1:5002`, menjalankan baseline `D:\Projects\Combine\elrise-demo-baseline-20261014`, bukan source yang sedang dikembangkan.
- Baseline mempertahankan `.env` dan database demo existing, serta menggunakan folder foto existing. Database/foto demo tidak dimigrasi atau direset selama tahap 1.
- Preview development: `http://127.0.0.1:5003`, memakai `.env.features-development`, database `elrise_features_dev_20261014`, secret serta nama cookie session tersendiri, dan folder foto `instance/features-development/attendance-runtime`. Cookie berbeda mencegah login development menimpa sesi demo pada hostname yang sama. Folder development lama tetap utuh; penggantian lokasi dilakukan saat nol referensi foto karena ACL identitas runtime berbeda.
- Preview development memakai akun seed development yang sama alamat emailnya; password bersumber dari `DEMO_PASSWORD` dalam konfigurasi privat. Tidak ada absensi atau selfie rekaan.
- Konfigurasi privat dan log tetap dikecualikan dari Git. Jangan memakai seed/kredensial development untuk production.

Jika proses belum berjalan, jalankan masing-masing di terminal terpisah dari direktori Elrise:

~~~powershell
& '..\elrise-demo-baseline-20261014\Start-Demo.ps1'
& '.\scripts\start_feature_development.ps1'
~~~

Jangan menjalankan launcher kedua untuk port yang sudah digunakan. Launcher baseline membutuhkan virtual environment Elrise yang sama; jangan mengubah dependency lingkungan demo saat presentasi.

### Migrasi database existing

`database/schema.sql` tetap merupakan schema inti. `init-db` pada database kosong menginisialisasi inti dan migrasi fitur. Pada database existing, `init-db` tidak otomatis menjalankan migrasi fitur. Jika melakukan import SQL manual, lanjutkan dengan migrasi eksplisit yang sesuai.

`migrate-db` default hanya dry run dan tidak mengubah schema/data. Penerapan memerlukan nama database yang sama dengan konfigurasi dan konfirmasi backup. Contoh berikut khusus lingkungan development terpisah, bukan database demo:

~~~powershell
$env:ELRISE_ENV_FILE = '.env.features-development'
$env:FLASK_SKIP_DOTENV = '1'
.\.venv\Scripts\python.exe -m flask --app wsgi migrate-db
# Setelah backup dan prosedur pemulihan disiapkan:
.\.venv\Scripts\python.exe -m flask --app wsgi migrate-db --apply --database elrise_features_dev_20261014 --backup-confirmed
~~~

`--backup-confirmed` tidak membuat atau memverifikasi backup otomatis. `ELRISE_ENV_FILE` memilih file konfigurasi terpisah; file yang tidak ditemukan menyebabkan startup gagal, bukan fallback ke konfigurasi demo. `FLASK_SKIP_DOTENV=1` mencegah Flask CLI memuat `.env` demo terlebih dahulu.

Migrasi ber-versi memakai checksum dan lock per database. Database aplikasi lain, schema inti yang tidak kompatibel, checksum berubah, serta versi migrasi tidak dikenal ditolak. DDL MySQL bukan transaksi yang bisa seluruhnya di-rollback; migrasi MVP dibuat tambahan/idempotent sehingga retry tidak menimpa konfigurasi. Recovery tetap memerlukan prosedur teruji. Startup HTTP tidak menjalankan migrasi otomatis; database lama tetap dapat menjalankan HRIS inti dan menampilkan pemberitahuan bahwa management fitur belum dirilis.

Verifikasi tahap 1 pada 14 Oktober 2026: 89 tes pytest lulus di database QA acak terpisah; smoke test Edge headless lulus, termasuk management fitur desktop/mobile, tanpa error JavaScript/CSP. Kamera/GPS pada smoke test disimulasikan, bukan bukti UAT perangkat nyata. Kesiapan production tetap mengikuti `Production.md` dan pengembangan selanjutnya mengikuti `Planning.md`.

### Koreksi absensi: tahap 2

- Karyawan: buka **Riwayat > Ajukan koreksi** (termasuk tanggal tanpa catatan), atau **Status koreksi** untuk memantau keputusan dan membatalkan pengajuan pending. Menu sidebar **Koreksi absensi** juga tersedia.
- Admin PT: buka **Koreksi absensi**, periksa badge pending, bandingkan jam asli/efektif/usulan, lalu setujui atau tolak dengan alasan. Hanya tenant yang sesuai dapat melihat dan memproses pengajuan.
- Salah jam masuk/pulang dan lupa check-out memakai catatan efektif sebagai acuan. Lupa absensi tanpa catatan memerlukan kedua jam; jadwal kantor saat pengajuan disimpan sebagai snapshot, bukan bukti GPS historis.
- Usulan menggunakan WIB pada satu tanggal, sejak tanggal masuk kerja dan dalam `ATTENDANCE_RETENTION_DAYS`, tanpa waktu masa depan. Jam pulang harus setelah jam masuk. Izin/cuti pending atau approved yang beririsan harus diselesaikan lebih dahulu.
- Satu pending per karyawan/tanggal, token request unik, row lock, serta transaksi pengajuan/keputusan/audit mencegah efek ganda. Retry atau keputusan yang sudah selesai ditolak 409. Jika absensi asli berubah saat pending, approval ditolak; batalkan/tolak lalu ajukan ulang. Penolakan wajib memiliki catatan.
- `app/utils/attendance.py` menjadi sumber kehadiran efektif untuk semua dashboard, riwayat, detail dan Excel. Payroll berikutnya harus memakainya juga. Koreksi approved tetap dihitung ketika entitlement OFF; OFF hanya menutup operasi koreksi, bukan menghapus data atau membatalkan keputusan.
- Catatan asli tidak ditimpa. Tanggal tanpa absensi asli tidak menghasilkan row `attendances`, koordinat, atau selfie buatan. Excel menambahkan sumber kehadiran, ID koreksi, dan jam asli; kolom GPS tetap bukti asli, bukan bukti jam koreksi.

Verifikasi 14 Oktober 2026: **136 tes pytest lulus**, termasuk 47 tes khusus koreksi; smoke test Edge desktop dan mobile 390px/360px lulus tanpa error JavaScript/CSP. Sensor browser tetap simulasi. Migrasi `0002_attendance_corrections` hanya diterapkan ke database development, sesudah dry-run dan backup SQL yang direstore ke database QA serta dicocokkan checksum 10 tabel. Data existing setelah migrasi tetap identik. Backup/manifest: `instance/features-development/backups/pre-phase2-20261014-185133/` (diabaikan Git).

Backup foto development lama tidak berhasil karena ACL; database development saat itu tidak memiliki absensi/referensi foto. Lokasi runtime baru diuji baca/tulis tanpa memindahkan foto. `.env` demo, database/foto demo, kredensial akun, serta Gajiku Live tidak berubah. Tahap 2 belum dipromosikan ke baseline presentasi.

**Retensi koreksi belum ditetapkan:** koreksi, audit, dan absensi yang dirujuk dipertahankan oleh `purge-data`; `erase-employee` menolak karyawan yang memiliki audit koreksi. Retensi foto tetap berlaku. Jangan menjanjikan penghapusan lengkap atau sign-off production sebelum kebijakan audit disepakati dan diuji.

**Rollback:** hentikan promosi dan nonaktifkan operasi koreksi jika bermasalah; baseline demo tetap tersedia. Jangan menjalankan downgrade schema, menghapus audit, atau restore backup otomatis. Kode tahap 1 tidak memahami koreksi approved, sehingga tidak boleh langsung digunakan untuk membaca database tahap 2 yang sudah memiliki koreksi. Rencana pemulihan data dan rilis kompatibel perlu disepakati terpisah.

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
- V1 mendukung shift dalam satu tanggal dan satu kantor penempatan per employee. Development tahap 2 mendukung koreksi melalui approval/audit; belum ada kalender libur nasional, offline attendance atau jadwal historis berlapis.
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

Foto kedaluwarsa dihapus dan path dikosongkan; riwayat biasa tersedia sampai retensi absensi. Catatan/pengajuan izin kedaluwarsa juga dihapus. Pengecualian tahap 2: koreksi, audit, dan absensi terkait dipertahankan sampai kebijakan retensinya disetujui. Jalankan dengan user deployment yang memiliki akses file; kegagalan penghapusan harus dimonitor. Backup, salinan export, file import dan log perlu kebijakan terpisah yang konsisten. File orphan akibat crash dan foto uji yang tidak lagi direferensikan perlu rekonsiliasi storage; job ini tidak menyapu sembarang file secara rekursif.

Untuk permohonan penghapusan yang sudah dinilai dan tidak terhalang kewajiban retensi: nonaktifkan karyawan, lalu operator menjalankan perintah berikut dengan konfirmasi interaktif. Perintah memerlukan client_id dan employee_id yang cocok. Karyawan dengan audit koreksi ditolak tanpa menghapus data; selain itu perintah menghapus akun/riwayat/foto karyawan nonaktif:

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
