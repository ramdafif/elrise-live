# Rencana MVP Payroll Elrise

Tanggal rencana: 14 Oktober 2026 (Asia/Jakarta).

Status: siap menjadi acuan implementasi bertahap. Dokumen ini adalah rencana, bukan pernyataan bahwa fitur sudah tersedia atau sudah layak production.

**Prioritas wajib selama pengerjaan: MVP demo yang sudah berjalan harus tetap tersedia dan lancar untuk presentasi.** Pengembangan payroll, koreksi absensi, dan kesiapan production tidak boleh mengganggu instance demo aktif. Jika perubahan berisiko merusak alur demo, kerjakan dan verifikasi di lingkungan terpisah terlebih dahulu, bukan langsung pada demo.

**Elrise punya payroll mandiri, lalu Gajiku menjadi integrasi opsional per client.** Client yang tidak memakai Gajiku tetap bisa menjalankan payroll lengkap. Scope saat ini adalah demo MVP; kode, database, dan koneksi live baru diubah saat tahap implementasi terkait dijalankan.

**Temuan Dari Repo**
- Elrise belum punya data gaji maupun payroll di `elrise/database/schema.sql:1`.
- Koreksi absensi belum punya alur pengajuan dan approval; jadi perlu dibangun end-to-end, bukan sekadar menyambungkan tombol. Riwayat absensi sekarang ada di `elrise/app/routes/employee.py:176`.
- Kode Gajiku yang diperiksa berfokus pada talangan/tarik gaji, limit, dan approval transaksi di `Gajiku-Live/app/routes/web.py:173`. Integrasinya nanti perlu membedakan **perhitungan payroll, talangan, dan pembayaran**.

## 1. Management Fitur Client — Superadmin

Tambahkan bagian **Fitur & Integrasi** pada detail client:
- **Payroll:** aktif/nonaktif; default OFF.
- **Koreksi absensi:** aktif/nonaktif; default ON.
- **Integrasi Gajiku:** diizinkan/tidak; default OFF, dengan syarat payroll aktif.
- Status koneksi terpisah: **nonaktif / belum dikonfigurasi / terhubung**. Toggle izin tidak langsung berarti sudah terhubung.
- Catat perubahan konfigurasi: siapa, kapan, dan nilai sebelum/sesudah.

Pembatasannya berlaku di backend juga, bukan hanya menyembunyikan menu. Admin PT tidak bisa mengaktifkan fitur yang belum diberikan Superadmin.

Struktur ini disiapkan supaya fitur lain bisa ditambahkan nanti tanpa menumpuk checkbox di tabel client.

### Aturan implementasi

- Default berlaku untuk client baru dan client existing yang belum memiliki konfigurasi fitur. Konfigurasi yang sudah disimpan tidak boleh ditimpa oleh migrasi berikutnya.
- Hanya Superadmin yang mengubah entitlement fitur. Admin PT tetap mengatur data dan kebijakan operasional dalam fitur yang diberikan.
- Pemeriksaan role, tenant, status layanan client, dan entitlement dilakukan di backend untuk setiap endpoint terkait.
- Menonaktifkan fitur memblokir akses operasionalnya, bukan menghapus data. Riwayat tetap disimpan dan tersedia kembali sesuai hak akses ketika fitur diaktifkan.
- Jika payroll OFF, operasi integrasi Gajiku juga tidak diizinkan, meskipun konfigurasi integrasi lama masih tersimpan.
- Pada MVP ini status Gajiku hanya nonaktif atau belum dikonfigurasi. Status terhubung tidak boleh ditampilkan sebelum koneksi nyata berhasil diverifikasi pada fase integrasi berikutnya.

## 2. Koreksi Absensi — Karyawan ke Admin PT

**Alur:** karyawan mengajukan → masuk antrean Admin PT yang sesuai → disetujui/ditolak → hasil terlihat oleh karyawan.

- Pengajuan berisi tanggal, jenis koreksi, jam yang diajukan, dan alasan wajib.
- Mendukung salah jam masuk/pulang, lupa check-out, serta lupa absensi ketika belum ada catatan sama sekali.
- Admin PT mendapat menu pengajuan, badge jumlah pending, detail catatan asli versus usulan, dan catatan keputusan.
- Karyawan bisa memantau status dan membatalkan pengajuan yang masih pending.
- Validasi mencegah pengajuan duplikat dan review lintas PT.

Status pengajuan: `pending`, `approved`, `rejected`, atau `canceled`. Pembatalan oleh karyawan hanya berlaku saat pending; penolakan oleh Admin PT wajib disertai alasan. Submit ulang atau review bersamaan tidak boleh menghasilkan pengajuan atau efek approval ganda.

**Catatan penting:** selfie, GPS, dan waktu absensi asli tetap dipertahankan. Koreksi disimpan sebagai catatan tambahan yang disetujui, bukan mengarang bukti GPS/selfie.

Riwayat, dashboard, laporan Excel, dan payroll harus membaca hasil koreksi yang sama supaya angkanya konsisten.

Gunakan satu mekanisme pembacaan kehadiran efektif: catatan asli ditambah koreksi yang disetujui. Mekanisme ini juga harus mendukung tanggal tanpa catatan absensi asli, tanpa membuat selfie atau koordinat palsu.

## 3. Payroll Mandiri — Scope Demo Pertama

Gunakan **payroll bulanan dulu**, dengan periode/cutoff yang bisa ditentukan Admin PT.

- **Profil gaji karyawan:** gaji pokok, tunjangan tetap, dan tanggal mulai berlaku.
- **Komponen per periode:** bonus, tambahan penghasilan, serta potongan dengan nama dan alasan yang jelas.
- **Preview payroll:** rincian per karyawan, rekap kehadiran efektif, total penghasilan, total potongan, dan take-home pay.
- **Alur:** draft → finalisasi → publikasi slip. Status pembayaran dicatat terpisah.
- **Output:** rekap Excel dan slip gaji di akun karyawan, dengan tampilan siap cetak.
- **Pembayaran demo:** pencatatan manual oleh Admin PT, bukan transfer bank otomatis.

Untuk MVP, absensi ditampilkan sebagai dasar review. **Jangan otomatis memotong gaji karena terlambat/absen sebelum kebijakan client ditentukan.** Potongan pajak/BPJS dan tambahan lembur bisa dicatat manual dulu; mesin perhitungan otomatisnya dibahas terpisah.

Payroll yang difinalisasi menyimpan snapshot gaji, komponen, dan kehadiran. Perubahan berikutnya tidak boleh diam-diam mengubah slip lama. Pengajuan koreksi pending dalam periode tersebut perlu diselesaikan sebelum finalisasi; koreksi setelah finalisasi masuk jalur adjustment.

### Aturan perhitungan dan validasi

- Gunakan gaji bulanan penuh sebagai dasar, tanpa prorata otomatis. Karyawan masuk di tengah periode, perubahan gaji, atau penyesuaian hari kerja ditangani melalui komponen manual yang terlihat jelas pada preview.
- Profil gaji memiliki tanggal berlaku. Profil yang dipakai harus ditampilkan pada preview dan disimpan dalam snapshot saat finalisasi.
- Karyawan yang masuk daftar payroll tetapi belum memiliki profil gaji ditandai untuk dilengkapi dan memblokir finalisasi, bukan otomatis dianggap bergaji Rp0.
- Semua nominal memakai rupiah bulat dan perhitungan integer/Decimal, bukan floating point. Nilai komponen tidak negatif; jenis penghasilan atau potongan menentukan pengaruhnya.
- Total penghasilan = gaji pokok + tunjangan tetap + tambahan penghasilan. Take-home pay = total penghasilan - total potongan.
- Take-home pay negatif memblokir finalisasi. Tidak boleh diam-diam dibulatkan menjadi nol atau diteruskan sebagai pembayaran.
- Cegah payroll reguler ganda untuk karyawan/periode yang sama, termasuk periode reguler dengan rentang tanggal tumpang tindih. Adjustment dibedakan dari payroll reguler dan memiliki referensi payroll asal serta alasan.
- Pengajuan koreksi pending untuk karyawan dan tanggal yang termasuk payroll harus diselesaikan sebelum finalisasi. Perubahan setelah finalisasi tidak menghitung ulang snapshot lama.

### Hak akses dan lifecycle

- Admin PT hanya mengelola payroll tenant sendiri. Karyawan hanya melihat slip sendiri yang sudah dipublikasikan; draft dan payroll final yang belum dipublikasikan tidak terlihat oleh karyawan.
- Finalisasi dan publikasi harus aman terhadap klik berulang atau request bersamaan. Payroll final tidak bisa diedit atau dihapus melalui alur draft.
- Status pembayaran terpisah dari status payroll: `unpaid` atau `paid`. Pencatatan paid hanya untuk payroll final, dilengkapi tanggal pembayaran, pencatat, dan catatan/referensi pembayaran.
- Pencatatan pembayaran manual tidak boleh dianggap sebagai bukti bahwa aplikasi sudah melakukan transfer bank.

## 4. Siapkan Jalur Integrasi Gajiku

Fase sekarang menyiapkan struktur dan batas integrasinya, **belum menghubungkan ke Gajiku Live**.

- Elrise menjadi sumber data karyawan, profil gaji, dan hasil payroll.
- Gajiku menjadi sumber transaksi talangan dan status penyelesaiannya.
- Identitas client/karyawan memakai mapping ID yang stabil, bukan hanya mencocokkan nama perusahaan atau email.
- Komponen potongan payroll dapat menyimpan referensi transaksi eksternal.
- Saat integrasi dibangun, transaksi harus direkonsiliasi dan tidak boleh terpotong dua kali karena sinkronisasi ulang.

Nanti alurnya: Elrise mengirim data yang disepakati → Gajiku mencatat talangan → transaksi yang memenuhi aturan settlement menjadi potongan payroll.

**Dasar gaji untuk limit Gajiku, penanggung biaya, dan kecocokan cutoff harus kita sepakati sebelum koneksi live.** Tidak perlu menggabungkan database atau menyalin seluruh aplikasi Gajiku ke Elrise.

### Batas fase MVP

- Siapkan batas modul/adapter integrasi, konfigurasi per client, dan dukungan referensi transaksi eksternal tanpa menjalankan sinkronisasi nyata.
- Jangan mengubah source, environment, akun, atau database Gajiku Live pada fase ini.
- Jangan menampilkan transaksi talangan atau potongan Gajiku rekaan sebagai transaksi live.
- Pada fase integrasi berikutnya, hanya transaksi yang memenuhi aturan settlement yang disepakati boleh menjadi potongan. Identitas transaksi eksternal harus mencegah transaksi yang sama dipotong pada dua payroll atau akibat retry sinkronisasi.

## 5. Urutan Implementasi

Implementasi dilakukan per tahap. Jalankan tes terarah pada setiap tahap, lalu regression menyeluruh pada tahap terakhir. Jangan menunggu semua fitur selesai untuk mulai menguji.

### Gate wajib pada setiap tahap

- [ ] Verifikasi perubahan di development/QA terpisah sebelum memperbarui instance demo; fitur yang belum selesai tidak ikut dirilis ke demo.
- [ ] Jalankan smoke test alur demo existing dan fitur yang akan dipresentasikan sebelum promosi rilis.
- [ ] Pastikan baseline demo yang sudah terverifikasi, backup yang diperlukan, dan cara rollback tersedia. Jika smoke test gagal, jangan promosikan perubahan ke demo.

### Tahap 1: Fondasi dan management fitur client

- [x] Siapkan schema tambahan dan migrasi ber-versi tanpa reset, DROP, atau TRUNCATE data existing.
- [x] Gunakan database khusus Elrise; jangan menjalankan init ulang pada database aplikasi lain. Sesuaikan guard schema dan alur maintenance terhadap tabel baru.
- [x] Tambahkan konfigurasi fitur, audit perubahan, UI Superadmin, dan pemeriksaan entitlement di backend.
- [x] Uji default client baru/existing, perubahan oleh Superadmin, penolakan perubahan oleh Admin PT, serta akses melalui URL langsung ketika fitur OFF.

Lulus jika konfigurasi per client tersimpan, akses konsisten di UI/backend, dan data existing tetap utuh.

Status 14 Oktober 2026: tahap 1 selesai di development/QA; belum dipromosikan ke demo presentasi. Hasil: 89 tes pytest lulus dan smoke test Edge desktop/mobile lulus tanpa error JavaScript/CSP. Guard fitur diuji melalui endpoint khusus tes; endpoint operasional payroll/koreksi baru dibangun pada tahap berikutnya.

Demo stabil tetap berjalan di port 5002 dari baseline `D:\Projects\Combine\elrise-demo-baseline-20261014`, dengan database/foto existing yang tidak dimigrasi. Preview development berjalan di port 5003 menggunakan `.env.features-development`, database `elrise_features_dev_20261014`, secret tersendiri, dan folder foto terpisah. Migrasi database demo hanya boleh dilakukan setelah backup/pemulihan disiapkan dan jadwal promosi disepakati.

### Tahap 2: Koreksi absensi end-to-end

- [x] Tambahkan pengajuan, riwayat/status karyawan, antrean dan badge Admin PT, serta approval/rejection dengan audit.
- [x] Terapkan pembacaan kehadiran efektif pada dashboard, riwayat, detail absensi, dan laporan Excel.
- [x] Uji salah jam, lupa check-out, tidak ada catatan asli, pembatalan pending, request/review ganda, dan isolasi tenant.

Lulus jika pengajuan muncul hanya di Admin PT yang tepat, hasil keputusan konsisten, dan bukti absensi asli tidak berubah.

Status 14 Oktober 2026: tahap 2 selesai di development/QA, belum dipromosikan ke demo presentasi. Hasil akhir: **136 tes pytest lulus** (89 regression existing + 47 tes koreksi) dan smoke test Edge desktop/mobile 390px/360px lulus tanpa error JavaScript/CSP. GPS/kamera tetap simulasi. Pengujian memakai database QA acak, bukan data demo atau Gajiku Live.

Preview port 5003: karyawan membuka **Riwayat > Ajukan koreksi / Status koreksi**, Admin PT membuka **Koreksi absensi** dengan badge pending. Jenis yang tersedia: salah jam masuk, salah jam pulang, lupa check-out, dan lupa absensi tanpa catatan. Pembatalan hanya pending, penolakan wajib beralasan. Token pengajuan, unique constraint, lock, dan transaksi audit mencegah efek ganda; perubahan catatan sejak pengajuan memblokir approval sampai diajukan ulang.

Migrasi tambahan `0002_attendance_corrections` diterapkan hanya ke `elrise_features_dev_20261014` setelah dry-run dan restore backup SQL ke database QA terpisah diverifikasi dengan checksum 10 tabel. Data existing dan konfigurasi fitur tetap identik setelah migrasi. Backup/manifest tersimpan di `instance/features-development/backups/pre-phase2-20261014-185133/`. Tidak ada migrasi/reset pada database demo.

Folder foto development lama tidak dapat dibaca oleh identitas runtime launcher. Karena database development terverifikasi memiliki nol absensi/referensi foto, konfigurasi privat development diarahkan ke `instance/features-development/attendance-runtime`; baca/tulis folder baru diuji. Folder lama, folder demo, secret, dan akun tidak diubah; tidak ada foto yang dipindahkan. Backup foto lama tidak diklaim berhasil, dan batasan ACL ini dicatat dalam manifest.

Kehadiran efektif membaca catatan asli ditambah koreksi approved melalui `app/utils/attendance.py`, termasuk saat entitlement kemudian OFF. OFF memblokir operasi koreksi, bukan membatalkan keputusan yang sudah sah. Tanggal tanpa catatan asli tidak membuat baris absensi/GPS/selfie palsu. Alur payroll tahap 3 wajib memakai mekanisme yang sama.

Batasan: satu tanggal WIB, tanpa shift lintas hari; usulan tidak boleh di masa depan/sebelum mulai kerja/di luar jendela retensi. Jadwal kantor saat pengajuan dipakai bila tidak ada snapshot absensi asli. Kebijakan penghapusan audit koreksi belum disepakati: `purge-data` mempertahankan koreksi, audit, dan absensi terkait; `erase-employee` ditahan bila ada audit koreksi. Retensi foto tetap berlaku. Finalisasi kebijakan ini tetap menjadi gap production.

Rollback/promosi: demo tetap memakai baseline port 5002 tanpa deployment tahap 2. Jika ada masalah development, hentikan promosi dan nonaktifkan operasi koreksi melalui entitlement; jangan menghapus migrasi/audit atau otomatis me-restore backup. Jangan downgrade kode tahap 1 ke database yang sudah berisi koreksi approved karena pembacaan kehadirannya belum memahami koreksi. Pemulihan data memerlukan prosedur dan persetujuan terpisah. Berikutnya tahap 3; payroll belum dibangun dan Gajiku Live belum dihubungkan.

### Tahap 3: Profil gaji dan draft payroll

- [ ] Tambahkan profil gaji bertanggal berlaku, komponen manual, periode/cutoff, daftar karyawan, dan preview payroll.
- [ ] Tampilkan kehadiran efektif dan peringatan profil gaji belum lengkap atau koreksi pending.
- [ ] Uji perhitungan nominal, tanpa prorata/potongan absensi otomatis, profil gaji tidak tersedia, take-home pay negatif, dan payroll reguler duplikat/tumpang tindih.

Lulus jika rincian dan total payroll dapat diverifikasi sebelum finalisasi, dengan kesalahan ditampilkan secara jelas.

### Tahap 4: Finalisasi, slip, dan pembayaran manual

- [ ] Bekukan snapshot, terapkan finalisasi/publikasi, dan siapkan adjustment beralasan untuk perubahan setelah finalisasi.
- [ ] Tambahkan slip karyawan siap cetak, export Excel, dan pencatatan pembayaran manual.
- [ ] Uji payroll terkunci, koreksi pending yang memblokir finalisasi, perubahan data setelah finalisasi, request bersamaan, dan privasi slip antar-karyawan/tenant.

Lulus jika slip sesuai snapshot, akses dibatasi untuk pemilik dan Admin PT terkait, dan perubahan data sumber tidak mengubah payroll final.

### Tahap 5: Kesiapan integrasi Gajiku

- [ ] Siapkan konfigurasi/kontrak integrasi per client, strategi mapping ID stabil, dan referensi eksternal pada komponen payroll.
- [ ] Pastikan izin integrasi bergantung pada payroll aktif dan status belum dikonfigurasi tampil jujur.
- [ ] Uji bahwa fase MVP tidak mengirim request ke Gajiku Live atau mengubah databasenya.

Lulus jika payroll mandiri berjalan tanpa Gajiku dan struktur dapat dilanjutkan ke integrasi nyata tanpa menggabungkan database.

### Tahap 6: Regression dan demo dua tenant

- [ ] Jalankan regression fitur existing: login/role, isolasi tenant, absensi GPS/selfie, izin/cuti, dan laporan.
- [ ] Jalankan skenario demo payroll dan koreksi pada PT A, sementara PT B tidak mendapat akses payroll ketika fiturnya OFF.
- [ ] Verifikasi halaman terkait pada desktop dan mobile; bedakan simulasi browser dari UAT kamera/GPS perangkat nyata.
- [ ] Perbarui dokumentasi dengan fitur yang benar-benar selesai, cara migrasi, hasil tes, dan batasan demo.

Lulus jika regression dan demo dua tenant berhasil, halaman dapat digunakan pada desktop/mobile, serta batasan yang belum diuji dicatat tanpa klaim production-ready.

Pengujian yang membuat/menghapus database uji hanya dijalankan pada lingkungan QA terpisah, bukan database demo aktif, aplikasi existing, atau Gajiku Live.

**Target demo:** Superadmin mengaktifkan payroll untuk PT A → karyawan mengajukan koreksi → Admin PT menyetujui → membuat dan memfinalisasi payroll → karyawan melihat slip. PT B tetap tidak bisa mengakses payroll jika fiturnya nonaktif.

## 6. Di Luar Scope Saat Ini

- Transfer bank/disbursement otomatis dan integrasi live Gajiku.
- Mesin pajak/BPJS, prorata, atau perhitungan lembur otomatis.
- Payroll harian/mingguan, shift kompleks, dan workflow approval payroll berlapis.
- Rebuild frontend, penggabungan database, atau pemindahan seluruh aplikasi Gajiku ke Elrise.
- Sign-off production; keamanan operasional, deployment, backup/restore, dan UAT nyata tetap memiliki checklist terpisah.

Fitur HRIS lain dibahas terpisah sebelum ditambahkan ke scope. **Default MVP: payroll bulanan, komponen fleksibel, pembayaran manual, koreksi dengan approval/audit, dan Gajiku belum tersambung.**

## 7. Kontinuitas Demo dan Pengembangan Production

### Lindungi instance demo untuk presentasi

- Pertahankan satu baseline rilis demo yang sudah terverifikasi. Instance demo menjalankan salinan rilis stabil, bukan direktori source yang sedang diedit atau proses development yang melakukan auto-reload.
- Pisahkan instance/direktori rilis, port, database, konfigurasi environment, dan penyimpanan foto demo dari development/QA. Tes atau migrasi percobaan tidak boleh menulis ke data demo.
- Jangan reset database, reseed, mengubah kredensial akun presentasi, atau mengubah konfigurasi demo tanpa persetujuan dan jadwal yang jelas.
- Fitur baru hanya masuk demo setelah alur end-to-end dan pemeriksaan aksesnya lulus. Feature flag saja bukan jaminan keamanan rilis: startup aplikasi, schema, template, dan fitur existing juga harus tetap kompatibel.
- Sebelum presentasi, sepakati periode freeze: tidak ada deployment, migrasi, atau perubahan konfigurasi pada instance demo selama persiapan akhir dan presentasi berlangsung.

### Verifikasi dan rollback rilis demo

- Smoke test mencakup login ketiga role, akses tenant, dashboard, absensi/riwayat, izin/cuti, laporan Excel, dan fitur baru yang benar-benar akan ditampilkan. Verifikasi pada perangkat/browser presentasi; jangan menganggap simulasi GPS/kamera sebagai bukti UAT perangkat nyata.
- Perubahan schema harus ber-versi, bersifat tambahan/kompatibel terlebih dahulu, dan diuji sebelum diterapkan ke demo. Jangan menjalankan migrasi eksperimental otomatis saat aplikasi demo startup.
- Sebelum update yang menyentuh data demo, siapkan backup database dan file terkait serta versi aplikasi/config yang cocok. Pastikan prosedur pemulihan dapat digunakan, bukan hanya memiliki file backup.
- Jika pembaruan gagal, hentikan promosi rilis dan pertahankan atau kembalikan instance demo ke baseline terverifikasi. Rollback harus mempertimbangkan data baru setelah backup; jangan otomatis restore, menghapus data, atau menjalankan migrasi destruktif.

### Tetap berkembang menuju production

- Pengembangan production tetap berlanjut di development/staging tanpa menjadikan instance demo sebagai tempat eksperimen. Gunakan satu codebase dengan rilis dan konfigurasi per lingkungan, bukan dua aplikasi yang berkembang terpisah.
- Sejak MVP, perubahan harus menjaga isolasi tenant, otorisasi, validasi backend, audit, migrasi aman, dan regression test. Hindari jalan pintas demo yang melemahkan kontrol keamanan atau harus dibuang saat production.
- Lanjutkan checklist production terpisah di `Production.md`: deployment HTTPS, pengelolaan secret, backup/restore, monitoring, retensi/privasi, dan UAT perangkat nyata. Kesiapan presentasi tidak sama dengan persetujuan go-live production.
- Catat hasil setiap tahap: fitur yang selesai, dampak pada demo, hasil tes, cara rollback, dan gap production yang masih terbuka.

**Kriteria utama: demo tetap siap dipresentasikan, fitur baru dirilis setelah terverifikasi, dan pengembangan production terus berjalan tanpa mengorbankan stabilitas demo.**
