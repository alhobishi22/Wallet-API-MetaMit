import os
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import logging

logger = logging.getLogger(__name__)

class GoogleDriveService:
    def __init__(self):
        try:
            # تحميل بيانات الاعتماد من المتغيرات البيئية
            credentials_info = {
                "type": "service_account",
                "project_id": os.environ.get('GOOGLE_PROJECT_ID'),
                "private_key_id": os.environ.get('GOOGLE_PRIVATE_KEY_ID'),
                "private_key": os.environ.get('GOOGLE_PRIVATE_KEY').replace('\\n', '\n'),
                "client_email": os.environ.get('GOOGLE_CLIENT_EMAIL'),
                "client_id": os.environ.get('GOOGLE_CLIENT_ID'),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": os.environ.get('GOOGLE_CLIENT_X509_CERT_URL')
            }
            
            # إنشاء بيانات الاعتماد
            credentials = service_account.Credentials.from_service_account_info(
                credentials_info,
                scopes=['https://www.googleapis.com/auth/drive.file']
            )
            
            # إنشاء خدمة Drive
            self.service = build('drive', 'v3', credentials=credentials)
            self.folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')
            
            logger.info("تم تهيئة خدمة Google Drive بنجاح")
        except Exception as e:
            logger.error(f"خطأ في تهيئة خدمة Google Drive: {str(e)}")
            raise

    def upload_file(self, file_data, filename, mime_type='image/jpeg'):
        """رفع ملف إلى Google Drive"""
        try:
            # إنشاء ملف في الذاكرة
            fh = io.BytesIO(file_data)
            
            # إعداد البيانات الوصفية للملف
            file_metadata = {
                'name': filename,
                'parents': [self.folder_id] if self.folder_id else None
            }
            
            # إنشاء كائن الوسائط
            media = MediaIoBaseUpload(
                fh,
                mimetype=mime_type,
                resumable=True
            )
            
            # رفع الملف
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()
            
            logger.info(f"تم رفع الملف {filename} بنجاح")
            return {
                'file_id': file.get('id'),
                'view_link': file.get('webViewLink')
            }
            
        except Exception as e:
            logger.error(f"خطأ في رفع الملف {filename}: {str(e)}")
            raise

    def delete_file(self, file_id):
        """حذف ملف من Google Drive"""
        try:
            self.service.files().delete(fileId=file_id).execute()
            logger.info(f"تم حذف الملف {file_id} بنجاح")
            return True
        except Exception as e:
            logger.error(f"خطأ في حذف الملف {file_id}: {str(e)}")
            return False