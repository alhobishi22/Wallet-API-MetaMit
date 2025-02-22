// المتغيرات العامة
let currentStep = 1;
const totalSteps = 3;
let idPhotoFile = null;
let selfiePhotoFile = null;

// المتغيرات العامة للكاميرا
let currentStream = null;
let facingMode = 'environment';

// دالة لإظهار رسائل الخطأ
function showError(message) {
    Swal.fire({
        title: 'خطأ!',
        text: message,
        icon: 'error',
        confirmButtonText: 'حسناً'
    });
}

// دالة لإظهار رسائل النجاح
function showSuccess(message) {
    Swal.fire({
        title: 'تم!',
        text: message,
        icon: 'success',
        confirmButtonText: 'حسناً'
    });
}

// دالة للانتقال إلى الخطوة التالية
function nextStep() {
    console.log('الانتقال إلى الخطوة التالية');
    console.log('الخطوة الحالية:', currentStep);

    // التحقق من صحة البيانات في الخطوة الحالية
    if (!validateCurrentStep()) {
        return;
    }

    // إخفاء الخطوة الحالية
    document.getElementById(`step${currentStep}`).style.display = 'none';

    // الانتقال إلى الخطوة التالية
    currentStep++;

    // عرض الخطوة التالية
    document.getElementById(`step${currentStep}`).style.display = 'block';

    // تحديث مؤشر الخطوات
    updateStepIndicator();

    console.log('تم الانتقال إلى الخطوة:', currentStep);
}

// دالة للعودة إلى الخطوة السابقة
function prevStep() {
    console.log('العودة إلى الخطوة السابقة');
    console.log('الخطوة الحالية:', currentStep);

    if (currentStep > 1) {
        // إخفاء الخطوة الحالية
        document.getElementById(`step${currentStep}`).style.display = 'none';
        
        // العودة إلى الخطوة السابقة
        currentStep--;
        
        // عرض الخطوة السابقة
        document.getElementById(`step${currentStep}`).style.display = 'block';
        
        // تحديث مؤشر الخطوات
        updateStepIndicator();
    }

    console.log('تم الانتقال إلى الخطوة:', currentStep);
}

// دالة للتحقق من صحة الخطوة الحالية
function validateCurrentStep() {
    console.log('التحقق من صحة الخطوة:', currentStep);
    
    switch (currentStep) {
        case 1:
            return validateStep1();
        case 2:
            return validateStep2();
        case 3:
            return validateStep3();
        default:
            return true;
    }
}

// دالة لتحديث مؤشر الخطوات
function updateStepIndicator() {
    console.log('تحديث مؤشر الخطوات');
    
    // تحديث جميع مؤشرات الخطوات
    for (let i = 1; i <= totalSteps; i++) {
        const indicator = document.querySelector(`.step-indicator[data-step="${i}"]`);
        if (indicator) {
            if (i === currentStep) {
                indicator.classList.add('active');
            } else {
                indicator.classList.remove('active');
            }
        }
    }
}

// دالة للتحقق من الخطوة الأولى
function validateStep1() {
    const fullName = document.getElementById('fullName').value;
    const idNumber = document.getElementById('idNumber').value;
    const phone = document.getElementById('phone').value;
    const address = document.getElementById('address').value;

    if (!fullName || !idNumber || !phone || !address) {
        showError('يرجى ملء جميع الحقول المطلوبة');
        return false;
    }

    if (!phone.startsWith('7') || phone.length !== 9 || !/^\d+$/.test(phone)) {
        showError('يجب أن يبدأ رقم الهاتف برقم 7 ويتكون من 9 أرقام');
        return false;
    }

    return true;
}

// دالة للتحقق من الخطوة الثانية
function validateStep2() {
    console.log('التحقق من الخطوة الثانية');
    const idPreview = document.getElementById('idPreview');
    if (!idPreview || idPreview.style.display === 'none' || !idPhotoFile) {
        showError('الرجاء التقاط صورة الهوية');
        return false;
    }
    console.log('تم التحقق من الخطوة الثانية بنجاح');
    return true;
}

// دالة للتحقق من الخطوة الثالثة
function validateStep3() {
    console.log('التحقق من الخطوة الثالثة');
    const selfiePreview = document.getElementById('selfiePreview');
    if (!selfiePreview || selfiePreview.style.display === 'none' || !selfiePhotoFile) {
        showError('الرجاء التقاط الصورة الشخصية');
        return false;
    }
    console.log('تم التحقق من الخطوة الثالثة بنجاح');
    return true;
}

// التحقق من وجود Telegram Web App
const tg = window.Telegram?.WebApp;

// دالة لإرسال النموذج
async function submitForm() {
    try {
        console.log('بدء إرسال النموذج...');

        // التحقق من وجود جميع البيانات المطلوبة
        const fullName = document.getElementById('fullName')?.value;
        const idNumber = document.getElementById('idNumber')?.value;
        const phone = document.getElementById('phone')?.value;
        const address = document.getElementById('address')?.value;

        if (!fullName || !idNumber || !phone || !address) {
            showError('يرجى ملء جميع الحقول المطلوبة');
            return;
        }

        if (!idPhotoFile) {
            showError('يرجى التقاط صورة الهوية');
            return;
        }

        if (!selfiePhotoFile) {
            showError('يرجى التقاط الصورة الشخصية');
            return;
        }

        // إظهار رسالة التحميل
        showLoading('جاري إرسال البيانات...');

        // تجهيز البيانات للإرسال
        const formData = new FormData();
        formData.append('full_name', fullName);
        formData.append('id_number', idNumber);
        formData.append('phone', phone);
        formData.append('address', address);

        // تحويل الصور من Base64 إلى Blob
        const idPhotoBlob = await fetch(idPhotoFile).then(r => r.blob());
        const selfiePhotoBlob = await fetch(selfiePhotoFile).then(r => r.blob());

        formData.append('id_photo', idPhotoBlob, 'id_photo.jpg');
        formData.append('selfie_photo', selfiePhotoBlob, 'selfie_photo.jpg');

        // إرسال البيانات إلى الخادم
        const response = await fetch('/submit', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error(`خطأ في الإرسال: ${response.status}`);
        }

        const result = await response.json();
        console.log('تم إرسال النموذج بنجاح:', result);

        // إخفاء رسالة التحميل
        hideLoading();

        // إظهار رسالة النجاح
        showSuccess('تم إرسال البيانات بنجاح!');

        // إعادة تعيين النموذج
        resetForm();

    } catch (error) {
        console.error('خطأ في إرسال النموذج:', error);
        hideLoading();
        showError('حدث خطأ أثناء إرسال البيانات. الرجاء المحاولة مرة أخرى.');
    }
}

// دالة لإعادة تعيين النموذج
function resetForm() {
    // إعادة تعيين الحقول
    document.getElementById('fullName').value = '';
    document.getElementById('idNumber').value = '';
    document.getElementById('phone').value = '';
    document.getElementById('address').value = '';

    // إعادة تعيين الصور
    idPhotoFile = null;
    selfiePhotoFile = null;

    // إخفاء معاينات الصور
    document.getElementById('idPreview').style.display = 'none';
    document.getElementById('selfiePreview').style.display = 'none';

    // إعادة تعيين أزرار الكاميرا
    document.getElementById('captureIdButton').style.display = 'block';
    document.getElementById('captureSelfieButton').style.display = 'block';
    document.getElementById('retakeIdButton').style.display = 'none';
    document.getElementById('retakeSelfieButton').style.display = 'none';

    // العودة إلى الخطوة الأولى
    currentStep = 1;
    for (let i = 1; i <= totalSteps; i++) {
        const step = document.getElementById(`step${i}`);
        if (step) {
            step.style.display = i === 1 ? 'block' : 'none';
        }
    }
    updateStepIndicator();
}

// دالة لإظهار رسالة التحميل
function showLoading(message) {
    Swal.fire({
        title: 'جاري التحميل...',
        text: message,
        allowOutsideClick: false,
        showConfirmButton: false,
        willOpen: () => {
            Swal.showLoading();
        }
    });
}

// دالة لإخفاء رسالة التحميل
function hideLoading() {
    Swal.close();
}

// دالة للتحقق من الخطوة الأولى
function validateStep1() {
    console.log('التحقق من الخطوة الأولى');
    const fullName = document.getElementById('fullName').value;
    const idNumber = document.getElementById('idNumber').value;
    const phone = document.getElementById('phone').value;
    const address = document.getElementById('address').value;

    if (!fullName) {
        showError('الرجاء إدخال الاسم الكامل');
        return false;
    }

    if (!idNumber) {
        showError('الرجاء إدخال رقم الهوية');
        return false;
    }

    if (!idNumber.match(/^\d{4,}$/)) {
        showError('رقم الهوية يجب أن يتكون من 4 أرقام على الأقل');
        return false;
    }

    if (!phone) {
        showError('الرجاء إدخال رقم الهاتف');
        return false;
    }

    if (!phone.match(/^7\d{8}$/)) {
        showError('يجب أن يبدأ رقم الهاتف برقم 7 ويتكون من 9 أرقام');
        return false;
    }

    if (!address) {
        showError('الرجاء إدخال عنوان السكن');
        return false;
    }

    console.log('تم التحقق من الخطوة الأولى بنجاح');
    return true;
}

// دالة للتحقق من الخطوة الثانية
function validateStep2() {
    console.log('التحقق من الخطوة الثانية');
    if (!idPhotoFile) {
        showError('الرجاء التقاط صورة الهوية');
        return false;
    }
    console.log('تم التحقق من الخطوة الثانية بنجاح');
    return true;
}

// دالة للتحقق من الخطوة الثالثة
function validateStep3() {
    console.log('التحقق من الخطوة الثالثة');
    if (!selfiePhotoFile) {
        showError('الرجاء التقاط الصورة الشخصية');
        return false;
    }
    console.log('تم التحقق من الخطوة الثالثة بنجاح');
    return true;
}

// دالة للتحقق من صحة البيانات
function validateData() {
    if (!validateStep1()) return false;
    if (!validateStep2()) return false;
    if (!validateStep3()) return false;
    return true;
}

// دالة لرفع الصورة إلى الخادم
async function uploadPhoto(file, type) {
    const formData = new FormData();
    formData.append('photo', file);
    formData.append('type', type);

    try {
        showLoading('جاري رفع الصورة...');
        const response = await fetch('/api/upload-photo', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || 'حدث خطأ في رفع الصورة');
        }

        hideLoading();
        return result.filename;
    } catch (error) {
        hideLoading();
        throw error;
    }
}

// دالة لبدء تشغيل الكاميرا
async function startCamera(isSelfie = false) {
    try {
        // إيقاف أي stream حالي
        if (currentStream) {
            currentStream.getTracks().forEach(track => track.stop());
        }

        // تحديد عنصر الفيديو المناسب
        const videoElement = isSelfie ? document.getElementById('selfieCamera') : document.getElementById('idCamera');
        
        if (!videoElement) {
            throw new Error('لم يتم العثور على عنصر الفيديو');
        }

        // الحصول على stream الكاميرا
        const constraints = {
            video: {
                facingMode: facingMode,
                width: { ideal: 1920 },
                height: { ideal: 1080 }
            }
        };

        currentStream = await navigator.mediaDevices.getUserMedia(constraints);
        videoElement.srcObject = currentStream;
        videoElement.style.display = 'block';

        // إخفاء الصورة المعاينة
        const previewElement = isSelfie ? document.getElementById('selfiePreview') : document.getElementById('idPreview');
        if (previewElement) {
            previewElement.style.display = 'none';
        }

        // إظهار زر تبديل الكاميرا
        const switchButton = isSelfie ? document.getElementById('switchSelfieCameraButton') : document.getElementById('switchIdCameraButton');
        if (switchButton) {
            switchButton.style.display = 'block';
        }

        // إظهار زر التقاط الصورة
        const captureButton = isSelfie ? document.getElementById('captureSelfieButton') : document.getElementById('captureIdButton');
        if (captureButton) {
            captureButton.style.display = 'block';
        }

        return true;
    } catch (error) {
        console.error('خطأ في تشغيل الكاميرا:', error);
        showError('حدث خطأ في تشغيل الكاميرا. يرجى التأكد من السماح بالوصول إلى الكاميرا والمحاولة مرة أخرى.');
        return false;
    }
}

// دالة لتبديل الكاميرا
async function switchCamera(isSelfie = false) {
    try {
        // تبديل وضع الكاميرا
        facingMode = facingMode === 'environment' ? 'user' : 'environment';
        
        // إعادة تشغيل الكاميرا
        await startCamera(isSelfie);
    } catch (error) {
        console.error('خطأ في تبديل الكاميرا:', error);
        showError('حدث خطأ في تبديل الكاميرا. يرجى المحاولة مرة أخرى.');
    }
}

// دالة لالتقاط الصورة
async function capturePhoto(isSelfie = false) {
    try {
        // التحقق من وجود stream الكاميرا
        if (!currentStream) {
            // إذا لم يكن هناك stream، قم بتشغيل الكاميرا أولاً
            const started = await startCamera(isSelfie);
            if (!started) return;
        } else {
            const videoElement = isSelfie ? document.getElementById('selfieCamera') : document.getElementById('idCamera');
            const previewElement = isSelfie ? document.getElementById('selfiePreview') : document.getElementById('idPreview');
            
            if (!videoElement || !previewElement) {
                throw new Error('لم يتم العثور على عناصر الفيديو أو المعاينة');
            }

            // إنشاء canvas لالتقاط الصورة
            const canvas = document.createElement('canvas');
            canvas.width = videoElement.videoWidth;
            canvas.height = videoElement.videoHeight;
            const context = canvas.getContext('2d');
            
            // رسم الصورة على canvas
            context.drawImage(videoElement, 0, 0, canvas.width, canvas.height);
            
            // تحويل الصورة إلى base64
            const photoData = canvas.toDataURL('image/jpeg');
            
            // حفظ الصورة في المتغير المناسب
            if (isSelfie) {
                selfiePhotoFile = photoData;
            } else {
                idPhotoFile = photoData;
            }
            
            // عرض الصورة في عنصر المعاينة
            previewElement.src = photoData;
            previewElement.style.display = 'block';
            videoElement.style.display = 'none';

            // إظهار زر إعادة التقاط الصورة
            const retakeButton = isSelfie ? document.getElementById('retakeSelfieButton') : document.getElementById('retakeIdButton');
            if (retakeButton) {
                retakeButton.style.display = 'block';
            }

            // إيقاف stream الكاميرا
            currentStream.getTracks().forEach(track => track.stop());
            currentStream = null;
        }
    } catch (error) {
        console.error('خطأ في التقاط الصورة:', error);
        showError('حدث خطأ أثناء التقاط الصورة. الرجاء المحاولة مرة أخرى.');
    }
}

// دالة لإعادة التقاط الصورة
async function retakePhoto(isSelfie = false) {
    try {
        // إعادة تشغيل الكاميرا
        await startCamera(isSelfie);
        
        // إعادة تعيين المتغيرات
        if (isSelfie) {
            selfiePhotoFile = null;
        } else {
            idPhotoFile = null;
        }
    } catch (error) {
        console.error('خطأ في إعادة التقاط الصورة:', error);
        showError('حدث خطأ أثناء إعادة تشغيل الكاميرا. الرجاء المحاولة مرة أخرى.');
    }
}

// إضافة مستمعات الأحداث للكاميرا
document.addEventListener('DOMContentLoaded', function() {
    // عناصر صورة الهوية
    const idVideo = document.getElementById('idCamera');
    const idPreview = document.getElementById('idPreview');
    const startIdButton = document.getElementById('startIdCamera');
    const switchIdButton = document.getElementById('switchIdCameraButton');
    const captureIdButton = document.getElementById('captureIdButton');
    const retakeIdButton = document.getElementById('retakeIdButton');

    // عناصر الصورة الشخصية
    const selfieVideo = document.getElementById('selfieCamera');
    const selfiePreview = document.getElementById('selfiePreview');
    const startSelfieButton = document.getElementById('startSelfieCamera');
    const switchSelfieButton = document.getElementById('switchSelfieCameraButton');
    const captureSelfieButton = document.getElementById('captureSelfieButton');
    const retakeSelfieButton = document.getElementById('retakeSelfieButton');

    // إضافة مستمعات الأحداث لصورة الهوية
    if (startIdButton) {
        startIdButton.addEventListener('click', () => startCamera(false));
    }
    if (switchIdButton) {
        switchIdButton.addEventListener('click', () => switchCamera(false));
    }
    if (captureIdButton) {
        captureIdButton.addEventListener('click', () => capturePhoto(false));
    }
    if (retakeIdButton) {
        retakeIdButton.addEventListener('click', () => retakePhoto(false));
    }

    // إضافة مستمعات الأحداث للصورة الشخصية
    if (startSelfieButton) {
        startSelfieButton.addEventListener('click', () => startCamera(true));
    }
    if (switchSelfieButton) {
        switchSelfieButton.addEventListener('click', () => switchCamera(true));
    }
    if (captureSelfieButton) {
        captureSelfieButton.addEventListener('click', () => capturePhoto(true));
    }
    if (retakeSelfieButton) {
        retakeSelfieButton.addEventListener('click', () => retakePhoto(true));
    }
});

// إضافة مستمع الحدث للنموذج
document.getElementById('kycForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    await submitForm();
});
