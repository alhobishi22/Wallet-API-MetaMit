// المتغيرات العامة
let currentStep = 1;
let idStream = null;
let selfieStream = null;
let formData = {
    fullName: '',
    idNumber: '',
    phone: '',
    idPhoto: '',
    selfiePhoto: ''
};

// التحقق من وجود Telegram Web App
const tg = window.Telegram?.WebApp;

// إعداد Telegram Web App
if (tg) {
    tg.ready();
    tg.expand();
}

// عند تحميل الصفحة
document.addEventListener('DOMContentLoaded', function() {
    console.log('تم تحميل الصفحة');
    initializeForm();
});

function initializeForm() {
    // إظهار الخطوة الأولى
    showStep(1);
    
    // إضافة مستمعي الأحداث
    setupNavigationButtons();
    setupCameraButtons();
    setupFormSubmission();
}

function setupNavigationButtons() {
    // أزرار التنقل
    const nextButtons = document.querySelectorAll('.btn-next');
    const prevButtons = document.querySelectorAll('.btn-prev');
    
    nextButtons.forEach(button => {
        button.addEventListener('click', handleNextStep);
    });
    
    prevButtons.forEach(button => {
        button.addEventListener('click', handlePrevStep);
    });
}

function setupCameraButtons() {
    // أزرار الكاميرا
    const cameraButtons = document.querySelectorAll('.camera-button');
    
    cameraButtons.forEach(button => {
        button.addEventListener('click', function() {
            const step = this.closest('.step');
            const isIdStep = step.id === 'step2';
            
            if (this.textContent.includes('فتح')) {
                startCamera(isIdStep);
            } else if (this.textContent.includes('التقاط')) {
                capturePhoto(isIdStep);
            } else if (this.textContent.includes('إعادة')) {
                retakePhoto(isIdStep);
            }
        });
    });
}

function setupFormSubmission() {
    // نموذج KYC
    const form = document.getElementById('kycForm');
    if (form) {
        form.addEventListener('submit', handleFormSubmit);
    }
}

function showStep(step) {
    console.log('الانتقال إلى الخطوة:', step);
    
    // إخفاء جميع الخطوات
    const steps = document.querySelectorAll('.step');
    steps.forEach(el => {
        el.style.display = 'none';
    });
    
    // إظهار الخطوة المطلوبة
    const targetStep = document.getElementById(`step${step}`);
    if (targetStep) {
        targetStep.style.display = 'block';
        currentStep = step;
        updateProgressBar();
    }
}

function updateProgressBar() {
    const progress = ((currentStep - 1) / 2) * 100;
    const progressBar = document.querySelector('.progress-bar');
    if (progressBar) {
        progressBar.style.width = `${progress}%`;
    }
}

async function handleNextStep() {
    console.log('محاولة الانتقال إلى الخطوة التالية من الخطوة:', currentStep);
    
    // التحقق من صحة البيانات
    if (currentStep === 1) {
        const fullName = document.getElementById('fullName').value;
        const idNumber = document.getElementById('idNumber').value;
        const phone = document.getElementById('phone').value;
        
        if (!fullName || !idNumber || !phone) {
            await Swal.fire({
                title: 'خطأ',
                text: 'الرجاء تعبئة جميع الحقول المطلوبة',
                icon: 'error',
                confirmButtonText: 'حسناً'
            });
            return;
        }
        
        formData.fullName = fullName;
        formData.idNumber = idNumber;
        formData.phone = phone;
    }
    
    if (currentStep === 2 && !formData.idPhoto) {
        await Swal.fire({
            title: 'خطأ',
            text: 'الرجاء التقاط صورة الهوية',
            icon: 'error',
            confirmButtonText: 'حسناً'
        });
        return;
    }
    
    if (currentStep < 3) {
        showStep(currentStep + 1);
    }
}

function handlePrevStep() {
    console.log('الرجوع إلى الخطوة السابقة من الخطوة:', currentStep);
    if (currentStep > 1) {
        showStep(currentStep - 1);
    }
}

async function startCamera(isIdCamera) {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: isIdCamera ? 'environment' : 'user'
            }
        });
        
        const video = document.getElementById(isIdCamera ? 'idVideo' : 'selfieVideo');
        const preview = document.getElementById(isIdCamera ? 'idPreview' : 'selfiePreview');
        const buttons = isIdCamera ? 
            document.querySelector('#step2').querySelectorAll('.camera-button') :
            document.querySelector('#step3').querySelectorAll('.camera-button');
        
        if (video && preview && buttons) {
            video.srcObject = stream;
            video.style.display = 'block';
            preview.style.display = 'none';
            
            if (isIdCamera) {
                idStream = stream;
            } else {
                selfieStream = stream;
            }
            
            // تحديث حالة الأزرار
            buttons[0].style.display = 'none'; // زر فتح الكاميرا
            buttons[1].style.display = 'inline-block'; // زر التقاط الصورة
            buttons[2].style.display = 'none'; // زر إعادة التقاط
        }
        
    } catch (error) {
        console.error('خطأ في الوصول إلى الكاميرا:', error);
        await Swal.fire({
            title: 'خطأ',
            text: 'لا يمكن الوصول إلى الكاميرا. الرجاء التأكد من السماح بالوصول إلى الكاميرا.',
            icon: 'error',
            confirmButtonText: 'حسناً'
        });
    }
}

async function capturePhoto(isIdPhoto) {
    const video = document.getElementById(isIdPhoto ? 'idVideo' : 'selfieVideo');
    const preview = document.getElementById(isIdPhoto ? 'idPreview' : 'selfiePreview');
    const buttons = isIdPhoto ? 
        document.querySelector('#step2').querySelectorAll('.camera-button') :
        document.querySelector('#step3').querySelectorAll('.camera-button');
    
    if (!video || !preview || !buttons) {
        console.error('لم يتم العثور على عناصر الكاميرا المطلوبة');
        return;
    }
    
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);
    
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg'));
    const photoFormData = new FormData();
    photoFormData.append('photo', blob);
    
    try {
        const response = await fetch('/api/upload-photo', {
            method: 'POST',
            body: photoFormData
        });
        
        const data = await response.json();
        if (response.ok) {
            if (isIdPhoto) {
                formData.idPhoto = data.filename;
            } else {
                formData.selfiePhoto = data.filename;
            }
            
            preview.src = URL.createObjectURL(blob);
            video.style.display = 'none';
            preview.style.display = 'block';
            
            // تحديث حالة الأزرار
            buttons[0].style.display = 'none'; // زر فتح الكاميرا
            buttons[1].style.display = 'none'; // زر التقاط الصورة
            buttons[2].style.display = 'inline-block'; // زر إعادة التقاط
            
            stopCamera(isIdPhoto);
        } else {
            throw new Error(data.error);
        }
    } catch (error) {
        console.error('خطأ في رفع الصورة:', error);
        await Swal.fire({
            title: 'خطأ',
            text: 'حدث خطأ أثناء رفع الصورة. الرجاء المحاولة مرة أخرى.',
            icon: 'error',
            confirmButtonText: 'حسناً'
        });
    }
}

function stopCamera(isIdCamera) {
    const stream = isIdCamera ? idStream : selfieStream;
    if (stream) {
        stream.getTracks().forEach(track => track.stop());
        if (isIdCamera) {
            idStream = null;
        } else {
            selfieStream = null;
        }
    }
}

function retakePhoto(isIdPhoto) {
    const video = document.getElementById(isIdPhoto ? 'idVideo' : 'selfieVideo');
    const preview = document.getElementById(isIdPhoto ? 'idPreview' : 'selfiePreview');
    const buttons = isIdPhoto ? 
        document.querySelector('#step2').querySelectorAll('.camera-button') :
        document.querySelector('#step3').querySelectorAll('.camera-button');
    
    if (isIdPhoto) {
        formData.idPhoto = '';
    } else {
        formData.selfiePhoto = '';
    }
    
    // إعادة تشغيل الكاميرا
    startCamera(isIdPhoto);
}

async function handleFormSubmit(event) {
    event.preventDefault();
    
    // التحقق من تحميل جميع الصور المطلوبة
    if (!formData.idPhoto || !formData.selfiePhoto) {
        await Swal.fire({
            title: 'خطأ',
            text: 'الرجاء التقاط جميع الصور المطلوبة',
            icon: 'error',
            confirmButtonText: 'حسناً'
        });
        return;
    }
    
    const form = {
        fullName: formData.fullName,
        idNumber: formData.idNumber,
        phone: formData.phone,
        idPhoto: formData.idPhoto,
        selfiePhoto: formData.selfiePhoto
    };
    
    // إضافة بيانات التلجرام إذا كان التطبيق يعمل داخل Telegram Web App
    if (tg) {
        form.telegram_data = {
            chat_id: tg.initDataUnsafe?.user?.id,
            username: tg.initDataUnsafe?.user?.username
        };
    }
    
    try {
        const response = await fetch('/api/submit-kyc', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(form)
        });
        
        const data = await response.json();
        
        if (response.ok) {
            // إغلاق Telegram Web App بعد نجاح التقديم
            if (tg) {
                tg.close();
            }
            
            window.location.href = `/check-status/${data.request_id}`;
        } else {
            await Swal.fire({
                title: 'خطأ',
                text: data.error || 'حدث خطأ أثناء تقديم الطلب',
                icon: 'error',
                confirmButtonText: 'حسناً'
            });
        }
    } catch (error) {
        await Swal.fire({
            title: 'خطأ',
            text: 'حدث خطأ في الاتصال',
            icon: 'error',
            confirmButtonText: 'حسناً'
        });
        console.error('Error:', error);
    }
}
