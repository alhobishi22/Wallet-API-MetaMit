import os
import logging
import cloudinary
import cloudinary.uploader
import cloudinary.api

logger = logging.getLogger(__name__)

class CloudinaryService:
    def __init__(self):
        try:
            # التحقق من وجود المتغيرات البيئية المطلوبة
            cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME')
            api_key = os.environ.get('CLOUDINARY_API_KEY')
            api_secret = os.environ.get('CLOUDINARY_API_SECRET')

            if not all([cloud_name, api_key, api_secret]):
                missing_vars = []
                if not cloud_name:
                    missing_vars.append('CLOUDINARY_CLOUD_NAME')
                if not api_key:
                    missing_vars.append('CLOUDINARY_API_KEY')
                if not api_secret:
                    missing_vars.append('CLOUDINARY_API_SECRET')
                raise ValueError(f"المتغيرات البيئية التالية مفقودة: {', '.join(missing_vars)}")

            # تهيئة Cloudinary
            cloudinary.config(
                cloud_name=cloud_name,
                api_key=api_key,
                api_secret=api_secret,
                secure=True
            )
            logger.info("تم تهيئة خدمة Cloudinary بنجاح")
        except Exception as e:
            logger.error(f"خطأ في تهيئة خدمة Cloudinary: {str(e)}")
            raise

    def upload_file(self, file_data, folder, public_id=None, resource_type="image"):
        """رفع ملف إلى Cloudinary"""
        try:
            # التحقق من نوع الملف
            if hasattr(file_data, 'read'):
                # إذا كان الملف من نوع FileStorage (من Flask)
                file_to_upload = file_data
            else:
                # إذا كان الملف بيانات ثنائية
                file_to_upload = io.BytesIO(file_data)
                if hasattr(file_data, 'content_type'):
                    file_to_upload.content_type = file_data.content_type

            # رفع الملف
            upload_params = {
                'folder': folder,
                'resource_type': resource_type,
                'unique_filename': True,
                'overwrite': False
            }
            if public_id:
                upload_params['public_id'] = public_id

            result = cloudinary.uploader.upload(
                file_to_upload,
                **upload_params
            )
            
            logger.info(f"تم رفع الملف بنجاح: {result['public_id']}")
            return {
                'public_id': result['public_id'],
                'url': result['secure_url'],
                'resource_type': result['resource_type']
            }
            
        except Exception as e:
            logger.error(f"خطأ في رفع الملف: {str(e)}")
            raise

    def delete_file(self, public_id, resource_type="image"):
        """حذف ملف من Cloudinary"""
        try:
            result = cloudinary.uploader.destroy(public_id, resource_type=resource_type)
            logger.info(f"تم حذف الملف {public_id} بنجاح")
            return result['result'] == 'ok'
        except Exception as e:
            logger.error(f"خطأ في حذف الملف {public_id}: {str(e)}")
            return False

    def create_folder(self, folder):
        """إنشاء مجلد في Cloudinary"""
        try:
            result = cloudinary.api.create_folder(folder)
            logger.info(f"تم إنشاء المجلد {folder} بنجاح")
            return True
        except Exception as e:
            logger.error(f"خطأ في إنشاء المجلد {folder}: {str(e)}")
            return False