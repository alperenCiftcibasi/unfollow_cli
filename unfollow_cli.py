import argparse
import getpass
import sys
import time
# Düzgün importlar
from atproto import Client, exceptions
# StrongRef importunu kaldırdık
from atproto_client import models # Hata tiplerini ve nsid'leri kullanmak için

# --- Sabitler ---
DEFAULT_FETCH_LIMIT = 100
FETCH_PAGE_DELAY = 0.7
UNFOLLOW_DELAY = 1.8       # Rate limit için kritik! Gerekirse artırın.
MAX_UNFOLLOW_ATTEMPTS = 3

# --- Yardımcı Fonksiyonlar (Renklendirme dahil - Değişiklik yok) ---
try:
    import colorama
    colorama.init()
    WARN_COLOR = colorama.Fore.YELLOW + colorama.Style.BRIGHT
    ERROR_COLOR = colorama.Fore.RED + colorama.Style.BRIGHT
    INFO_COLOR = colorama.Fore.GREEN + colorama.Style.BRIGHT
    STATUS_COLOR = colorama.Style.RESET_ALL
    RESET_COLOR = colorama.Style.RESET_ALL

    def print_warning(message): print(f"{WARN_COLOR}UYARI: {message}{RESET_COLOR}", file=sys.stdout)
    def print_error(message): print(f"{ERROR_COLOR}HATA: {message}{RESET_COLOR}", file=sys.stderr)
    def print_info(message): print(f"{INFO_COLOR}BİLGİ: {message}{RESET_COLOR}", file=sys.stdout)
    def print_status(message): print(f"{STATUS_COLOR}DURUM: {message}{RESET_COLOR}", file=sys.stdout)

except ImportError:
    def print_warning(message): print(f"UYARI: {message}", file=sys.stdout)
    def print_error(message): print(f"HATA: {message}", file=sys.stderr)
    def print_info(message): print(f"BİLGİ: {message}", file=sys.stdout)
    def print_status(message): print(f"DURUM: {message}", file=sys.stdout)


# --- Çekirdek Fonksiyonlar ---

def login_bsky(username, app_password):
    """Bluesky'a giriş yapar ve client nesnesini döndürür."""
    print_status(f"'{username}' olarak Bluesky'a bağlanılıyor...")
    try:
        client = Client() # Basit başlangıç
        client.login(username, app_password)
        profile_info = client.me
        if not profile_info or not profile_info.did:
             raise Exception("Giriş başarılı ancak profil bilgisi alınamadı.")
        print_info(f"Giriş başarılı: {profile_info.handle} (DID: {profile_info.did})")
        return client
    except exceptions.UnauthorizedError:
        print_error("Geçersiz Kullanıcı Adı veya Uygulama Şifresi!")
        return None
    except Exception as e:
        print_error(f"Giriş sırasında beklenmedik bir hata oluştu: {e}")
        import traceback
        traceback.print_exc()
        return None

# === YENİ GET_ALL_FOLLOWS FONKSİYONU ===
def get_all_follows(client):
    """Kullanıcının KENDİ 'app.bsky.graph.follow' kayıtlarını listeleyerek,
    takip ettiği kişilerin {did: record_uri} sözlüğünü alır."""
    my_did = client.me.did
    following_map = {} # {followed_did: record_uri}
    cursor = None
    print_status("Kendi takip kayıtları listeleniyor (listRecords)...")
    page_count = 0
    record_count = 0
    processed_records = 0

    while True:
        page_count += 1
        # print_status(f"  -> Sayfa {page_count} isteniyor...") # Çok fazla çıktı üretebilir, kapalı tutalım
        try:
            # Kendi repomuzdaki app.bsky.graph.follow kayıtlarını çek
            response = client.com.atproto.repo.list_records(models.ComAtprotoRepoListRecords.Params(
                repo=my_did,
                collection=models.ids.AppBskyGraphFollow, # 'app.bsky.graph.follow'
                limit=DEFAULT_FETCH_LIMIT,
                cursor=cursor
            ))

            if not response or not hasattr(response, 'records') or not response.records:
                print_info(f"Takip kayıtları listesinin sonuna ulaşıldı (Toplam {len(following_map)} geçerli kayıt bulundu).")
                break

            count_on_page = len(response.records)
            record_count += count_on_page
            # print_status(f"  -> Sayfa {page_count}: {count_on_page} kayıt alındı (Toplam {record_count})... İşleniyor...") # Çok fazla çıktı üretebilir

            for record in response.records:
                processed_records += 1
                record_uri = record.uri
                record_value = record.value

                if isinstance(record_value, dict) and 'subject' in record_value:
                    followed_did = record_value['subject']
                    following_map[followed_did] = record_uri
                elif hasattr(record_value, 'subject'):
                    followed_did = record_value.subject
                    following_map[followed_did] = record_uri
                else:
                    # Bu durumda kayıt URI'sini loglayabiliriz ama takip edilen DID'i bilemeyiz.
                    print_warning(f"  -> Geçersiz takip kaydı formatı (subject yok): URI={record_uri}")

            print_status(f"  -> Sayfa {page_count} işlendi. (İncelenen Kayıt: {record_count}, Bulunan Takip: {len(following_map)})")

            cursor = getattr(response, 'cursor', None)
            if not cursor:
                print_info(f"Takip kayıtları listesi için başka sayfa yok (Toplam {len(following_map)} geçerli kayıt bulundu).")
                break

            time.sleep(FETCH_PAGE_DELAY) # Sayfalar arası bekle

        # Hata yakalama
        except exceptions.NetworkError as ne:
            wait_time = 60
            if hasattr(ne, 'response') and ne.response and hasattr(ne.response, 'status_code'):
                 if ne.response.status_code == 429:
                     print_error(f"API Rate Limit Aşıldı (listRecords - HTTP 429)! {wait_time:.1f} saniye bekleniyor...")
                     time.sleep(wait_time)
                 else:
                     print_error(f"Ağ/HTTP Hatası (listRecords - Sayfa {page_count}): {ne.response.status_code} - {ne}. 5 saniye sonra tekrar denenecek...")
                     time.sleep(5)
            else:
                 print_error(f"Ağ Hatası (listRecords - Sayfa {page_count}): {ne}. 5 saniye sonra tekrar denenecek...")
                 time.sleep(5)
        except Exception as e:
            print_error(f"Takip kayıtlarını listelerken beklenmedik hata (Sayfa {page_count}): {e}. 5 saniye sonra tekrar denenecek...")
            import traceback
            traceback.print_exc()
            time.sleep(5)

    print_info(f"Kendi repo taraması tamamlandı. Toplam {processed_records} kayıt incelendi, {len(following_map)} takip eşleşmesi bulundu.")
    return following_map
# === ESKİ GET_ALL_FOLLOWS BİTTİ ===


def get_all_followers(client):
    """Kullanıcıyı takip eden TÜM kişilerin DID'lerini bir set olarak alır."""
    my_did = client.me.did
    followers_set = set()
    cursor = None
    print_status("Takipçiler listesi alınıyor...")
    page_count = 0
    record_count = 0 # Takipçi sayısını da sayalım
    while True:
        page_count += 1
        try:
            response = client.app.bsky.graph.get_followers(
                params={'actor': my_did, 'limit': DEFAULT_FETCH_LIMIT, 'cursor': cursor}
            )
            if not response or not hasattr(response, 'followers') or not response.followers:
                print_info(f"Takipçiler listesinin sonuna ulaşıldı (Toplam {len(followers_set)} takipçi).")
                break

            count_on_page = len(response.followers)
            record_count += count_on_page
            for follower in response.followers:
                 if hasattr(follower, 'did'):
                    followers_set.add(follower.did)
                 else:
                    print_warning(f"  -> Geçersiz takipçi verisi (DID yok): {follower}")

            print_status(f"  -> Takipçi Sayfa {page_count}: {count_on_page} kişi alındı (Toplam: {len(followers_set)})")

            cursor = getattr(response, 'cursor', None)
            if not cursor:
                print_info(f"Takipçiler listesi için başka sayfa yok (Toplam {len(followers_set)} takipçi).")
                break

            time.sleep(FETCH_PAGE_DELAY)

        except exceptions.NetworkError as ne:
            wait_time = 60
            if hasattr(ne, 'response') and ne.response and hasattr(ne.response, 'status_code'):
                 if ne.response.status_code == 429:
                     print_error(f"API Rate Limit Aşıldı (getFollowers - HTTP 429)! {wait_time:.1f} saniye bekleniyor...")
                     time.sleep(wait_time)
                 else:
                     print_error(f"Ağ/HTTP Hatası (getFollowers - Sayfa {page_count}): {ne.response.status_code} - {ne}. 5 saniye sonra tekrar denenecek...")
                     time.sleep(5)
            else:
                 print_error(f"Ağ Hatası (getFollowers - Sayfa {page_count}): {ne}. 5 saniye sonra tekrar denenecek...")
                 time.sleep(5)
        except Exception as e:
            print_error(f"Takipçileri alırken beklenmedik hata (Sayfa {page_count}): {e}. 5 saniye sonra tekrar denenecek...")
            time.sleep(5)

    return followers_set

def unfollow_user_by_uri(client, record_uri):
    """Verilen takip kaydı URI'sini kullanarak kullanıcıyı takipten çıkar."""
    try:
        parts = record_uri.split('/')
        if len(parts) < 5 or parts[3] != models.ids.AppBskyGraphFollow: # 'app.bsky.graph.follow'
            print_error(f"Geçersiz takip kaydı URI formatı: {record_uri}")
            return False

        # repo_did = parts[2] # Bu bilgiye aslında gerek yok, client.me.did kullanıyoruz
        collection = parts[3]
        rkey = parts[4]

        client.com.atproto.repo.delete_record(data=models.ComAtprotoRepoDeleteRecord.Data(
            repo=client.me.did,
            collection=collection,
            rkey=rkey
        ))
        return True

    except exceptions.NetworkError as ne:
         if hasattr(ne, 'response') and ne.response and hasattr(ne.response, 'status_code'):
             if ne.response.status_code == 429:
                 wait_time = 65
                 print_error(f"   !! API Rate Limit Aşıldı (Unfollow - HTTP 429)! {wait_time:.1f} saniye bekleniyor...")
                 time.sleep(wait_time)
                 return None # Tekrar dene
             else:
                 error_content = str(ne.response.content) if hasattr(ne.response, 'content') else str(ne)
                 if 'record not found' in error_content.lower() or 'could not find record' in error_content.lower():
                      # print_info(f"   -> Kayıt bulunamadı (muhtemelen zaten takipten çıkılmış): RKEY={rkey}")
                      return "already_unfollowed" # Özel durum
                 else:
                      print_error(f"   !! Ağ/HTTP Hatası (Unfollow - {ne.response.status_code}): RKEY={rkey} - {error_content}")
                      return False # Başarısız
         else:
             print_error(f"   !! Ağ Hatası (Unfollow): RKEY={rkey} - {ne}")
             return None # Tekrar dene

    except exceptions.AtProtocolError as ape:
         error_str = str(ape).lower()
         # Bazen AtProtocolError içinde de 'Record not found' gelebilir
         if 'record not found' in error_str or 'could not find record' in error_str:
              # print_info(f"   -> Kayıt bulunamadı (muhtemelen zaten takipten çıkılmış): RKEY={rkey}")
              return "already_unfollowed" # Özel durum
         else:
              print_error(f"   !! ATProto Hatası (Unfollow): RKEY={rkey} - {ape}")
              return False
    except Exception as e:
        print_error(f"   !! Beklenmedik Hata (Unfollow): RKEY={rkey} - {e}")
        import traceback
        traceback.print_exc()
        return False

# --- Ana İşlem ---
def main():
    parser = argparse.ArgumentParser(
        description="Bluesky'da sizi takip etmeyen kullanıcıları otomatik olarak takipten çıkarır.",
        epilog="Örnek: python unfollow_cli.py -u kullanici.bsky.social"
    )
    parser.add_argument("-u", "--username", required=True, help="Bluesky kullanıcı adınız")
    parser.add_argument("-p", "--password", help="Bluesky Uygulama Şifreniz. Boş bırakılırsa sorulacaktır.")
    parser.add_argument("--yes", action="store_true", help="Onay sorusunu atla.")
    parser.add_argument("--delay", type=float, default=UNFOLLOW_DELAY, help=f"Takipten çıkarma işlemleri arası bekleme (sn, varsayılan: {UNFOLLOW_DELAY})")

    args = parser.parse_args()

    username = args.username
    app_password = args.password
    unfollow_op_delay = args.delay

    if not app_password:
        print_info("Bluesky Uygulama Şifrenizi girin (Ana şifre DEĞİL!):")
        app_password = getpass.getpass("Uygulama Şifresi: ")
        if not app_password:
            print_error("Uygulama şifresi girilmedi. Çıkılıyor.")
            sys.exit(1)

    client = login_bsky(username, app_password)
    if not client:
        sys.exit(1)

    try:
        following_map = get_all_follows(client) # Yeni fonksiyonu çağır
        followers_set = get_all_followers(client)

        following_dids_with_uri = set(following_map.keys())

        if not following_dids_with_uri:
            print_info("Takip edilen kimse bulunamadı veya kayıtları listelenemedi.")
            sys.exit(0)

        dids_to_unfollow = following_dids_with_uri - followers_set
        count_to_unfollow = len(dids_to_unfollow)

        if count_to_unfollow == 0:
            print_info("Sizi takip etmeyen kimse bulunamadı. İşlem tamamlandı.")
            sys.exit(0)

        print_info(f"\nToplam {len(following_dids_with_uri)} kişi takip ediliyor (kayıtları bulundu).")
        print_info(f"Toplam {len(followers_set)} takipçiniz var.")
        print_warning(f"{count_to_unfollow} kişi takip ediliyor ancak sizi geri takip etmiyor.")

        if not args.yes:
            confirm = input(f"\n{count_to_unfollow} kişiyi takipten çıkmak istediğinizden emin misiniz? (yes/no): ").lower().strip()
            if confirm != 'yes':
                print_info("İşlem iptal edildi.")
                sys.exit(0)

        print_status(f"\nTakipten çıkarma işlemi başlıyor (Her işlem arası {unfollow_op_delay} sn bekleme)...")
        unfollowed_count = 0
        failed_count = 0
        skipped_already_unfollowed = 0

        for i, did in enumerate(list(dids_to_unfollow)):
            record_uri = following_map.get(did)
            if not record_uri:
                 print_error(f" [{i+1}/{count_to_unfollow}] HATA: DID {did[-6:]}... için URI bulunamadı, atlanıyor.")
                 failed_count += 1
                 continue

            print_status(f"[{i+1}/{count_to_unfollow}] Kullanıcı DID ...{did[-6:]} (URI: ...{record_uri.split('/')[-1]}) takipten çıkarılıyor...")

            success = False
            attempts = 0
            while attempts < MAX_UNFOLLOW_ATTEMPTS:
                attempts += 1
                result = unfollow_user_by_uri(client, record_uri)

                if result is True:
                    success = True
                    unfollowed_count += 1
                    # print_info(f"  -> Başarılı: DID ...{did[-6:]}") # Çok fazla çıktı
                    break
                elif result == "already_unfollowed": # Özel durumu kontrol et
                    success = True
                    skipped_already_unfollowed += 1
                    # print_info(f"  -> Zaten Takip Edilmiyor: DID ...{did[-6:]}") # Çok fazla çıktı
                    break
                elif result is None: # Tekrar dene
                    print_info(f"   -> Deneme {attempts}/{MAX_UNFOLLOW_ATTEMPTS} - Tekrar denenecek...")
                else: # result is False - Kalıcı hata
                    break # İç döngüden çık

            if not success:
                failed_count += 1
                # Başarısız mesajı zaten fonksiyonda yazdırılıyor

            time.sleep(unfollow_op_delay)


        print("\n--- İşlem Tamamlandı ---")
        print_info(f"Başarıyla Takipten Çıkarılan: {unfollowed_count}")
        print_info(f"Zaten Takip Edilmeyen/Kayıt Bulunamayan: {skipped_already_unfollowed}")
        print_warning(f"Takipten Çıkarılamayan (Hata): {failed_count}")
        print("------------------------")

    except Exception as e:
        print_error(f"Ana işlem sırasında beklenmedik bir hata oluştu: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        pass


if __name__ == "__main__":
    main()