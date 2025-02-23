// متغيرات عامة
let currentStep = 1;
let idPhotoBlob = null;
let selfiePhotoBlob = null;
let currentFacingMode = 'environment';
let isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);

// تهيئة Telegram WebApp
const telegram = window.Telegram.WebApp;
telegram.ready();
telegram.expand();

// تحديث مؤشرات الخطوات
function updateStepIndicators() {
    document.querySelectorAll('.step-indicator').forEach(indicator => {
        const step = parseInt(indicator.dataset.step);
        if (step === currentStep) {
            indicator.classList.add('active');
        } else {
            indicator.classList.remove('active');
        }
    });
}

// التحقق من صحة البيانات
function validateStep1() {
    const fullName = document.getElementById('fullName').value;
    const idNumber = document.getElementById('idNumber').value;
    const phone = document.getElementById('phone').value;
    const address = document.getElementById('address').value;

    if (!fullName || fullName.trim().split(' ').length < 4) {
        Swal.fire({
            icon: 'error',
            title: 'خطأ',
            text: 'يرجى إدخال الاسم الرباعي الكامل'
        });
        return false;
    }

    if (!idNumber || idNumber.length < 4) {
        Swal.fire({
            icon: 'error',
            title: 'خطأ',
            text: 'يرجى إدخال رقم هوية صحيح (4 أرقام على الأقل)'
        });
        return false;
    }

    if (!phone || !phone.startsWith('7') || phone.length !== 9 || !/^\d+$/.test(phone)) {
        Swal.fire({
            icon: 'error',
            title: 'خطأ',
            text: 'يرجى إدخال رقم جوال صحيح (يبدأ برقم 7 ويتكون من 9 أرقام)'
        });
        return false;
    }

    if (!address || address.trim().length < 10) {
        Swal.fire({
            icon: 'error',
            title: 'خطأ',
            text: 'يرجى إدخال عنوان صحيح'
        });
        return false;
    }

    return true;
}

function validateStep2() {
    if (!idPhotoBlob) {
        Swal.fire({
            icon: 'error',
            title: 'خطأ',
            text: 'يرجى التقاط صورة الهوية'
        });
        return false;
    }
    return true;
}

function validateStep3() {
    if (!selfiePhotoBlob) {
        Swal.fire({
            icon: 'error',
            title: 'خطأ',
            text: 'يرجى التقاط الصورة الشخصية'
        });
        return false;
    }
    return true;
}

// التأكد من وجود دعم للكاميرا
async function checkCameraSupport() {
    try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const cameras = devices.filter(device => device.kind === 'videoinput');
        return cameras.length > 0;
    } catch (error) {
        console.error('خطأ في فحص الكاميرا:', error);
        return false;
    }
}

// طلب إذن الوصول للكاميرا
async function requestCameraPermission() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: true });
        stream.getTracks().forEach(track => track.stop());
        return true;
    } catch (error) {
        console.error('خطأ في طلب إذن الكاميرا:', error);
        return false;
    }
}

// تهيئة الكاميرا
async function initCamera(videoElement, facingMode = 'environment') {
    try {
        // إيقاف أي تدفق حالي للكاميرا
        if (window.stream) {
            window.stream.getTracks().forEach(track => track.stop());
        }

        // تحديد خيارات الكاميرا
        let constraints = {
            video: {
                facingMode: facingMode
            }
        };

        // إضافة دقة مناسبة للجهاز
        if (isMobile) {
            // للهواتف المحمولة
            constraints.video = {
                facingMode: facingMode,
                width: { min: 640, ideal: 1280, max: 1920 },
                height: { min: 480, ideal: 720, max: 1080 }
            };
        } else {
            // للأجهزة المكتبية
            constraints.video = {
                facingMode: facingMode,
                width: { min: 1280, ideal: 1920 },
                height: { min: 720, ideal: 1080 }
            };
        }

        // محاولة الحصول على تدفق الكاميرا
        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        window.stream = stream;

        // إعداد عنصر الفيديو
        videoElement.srcObject = stream;
        videoElement.style.display = 'block';

        // انتظار تحميل البيانات الوصفية للفيديو
        await new Promise((resolve) => {
            videoElement.onloadedmetadata = () => {
                videoElement.play().catch(console.error);
                resolve();
            };
        });

        // تحديث واجهة المستخدم
        if (isMobile) {
            document.getElementById('switchIdCameraButton').style.display = 'block';
            document.getElementById('switchSelfieCameraButton').style.display = 'block';
        }

        return true;
    } catch (error) {
        console.error('خطأ في تهيئة الكاميرا:', error);

        let errorMessage = 'يرجى التأكد من السماح بالوصول إلى الكاميرا وإعادة المحاولة';
        if (error.name === 'NotAllowedError') {
            errorMessage = 'تم رفض الوصول إلى الكاميرا. يرجى السماح بالوصول من إعدادات المتصفح.';
        } else if (error.name === 'NotFoundError') {
            errorMessage = 'لم يتم العثور على كاميرا متصلة بجهازك.';
        } else if (error.name === 'NotReadableError') {
            errorMessage = 'لا يمكن الوصول إلى الكاميرا. يرجى التأكد من عدم استخدامها من قبل تطبيق آخر.';
        }

        await Swal.fire({
            icon: 'error',
            title: 'خطأ في الكاميرا',
            text: errorMessage,
            confirmButtonText: 'حسناً'
        });
        return false;
    }
}

// الانتقال إلى الخطوة التالية
async function nextStep() {
    let isValid = false;
    
    switch (currentStep) {
        case 1:
            isValid = validateStep1();
            if (isValid) {
                const hasCamera = await checkCameraSupport();
                if (!hasCamera) {
                    await Swal.fire({
                        icon: 'error',
                        title: 'خطأ',
                        text: 'لم يتم العثور على كاميرا'
                    });
                    return;
                }
                
                const hasPermission = await requestCameraPermission();
                if (!hasPermission) {
                    await Swal.fire({
                        icon: 'error',
                        title: 'خطأ',
                        text: 'يرجى السماح بالوصول إلى الكاميرا'
                    });
                    return;
                }
            }
            break;
        case 2:
            isValid = validateStep2();
            break;
        default:
            isValid = true;
    }

    if (isValid) {
        document.getElementById(`step${currentStep}`).style.display = 'none';
        currentStep++;
        document.getElementById(`step${currentStep}`).style.display = 'block';
        updateStepIndicators();

        if (currentStep === 2) {
            const video = document.getElementById('idCamera');
            await initCamera(video, currentFacingMode);
        } else if (currentStep === 3) {
            const video = document.getElementById('selfieCamera');
            await initCamera(video, 'user');
        }
    }
}

// الرجوع إلى الخطوة السابقة
function prevStep() {
    if (currentStep > 1) {
        // إيقاف الكاميرا إذا كانت قيد التشغيل
        if (window.stream) {
            window.stream.getTracks().forEach(track => track.stop());
        }
        
        document.getElementById(`step${currentStep}`).style.display = 'none';
        currentStep--;
        document.getElementById(`step${currentStep}`).style.display = 'block';
        updateStepIndicators();
    }
}

// التقاط صورة
function capturePhoto(isSelfie) {
    const video = document.getElementById(isSelfie ? 'selfieCamera' : 'idCamera');
    const canvas = document.createElement('canvas');
    
    // تعيين أبعاد الصورة
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    
    // التقاط الصورة
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0);

    // تحويل الصورة إلى blob
    canvas.toBlob(blob => {
        if (isSelfie) {
            selfiePhotoBlob = blob;
            document.getElementById('selfiePreview').src = URL.createObjectURL(blob);
            document.getElementById('selfiePreview').style.display = 'block';
            document.getElementById('selfieCamera').style.display = 'none';
            document.getElementById('captureSelfieButton').style.display = 'none';
            document.getElementById('retakeSelfieButton').style.display = 'block';
        } else {
            idPhotoBlob = blob;
            document.getElementById('idPreview').src = URL.createObjectURL(blob);
            document.getElementById('idPreview').style.display = 'block';
            document.getElementById('idCamera').style.display = 'none';
            document.getElementById('captureIdButton').style.display = 'none';
            document.getElementById('retakeIdButton').style.display = 'block';
        }

        // إيقاف الكاميرا
        if (window.stream) {
            window.stream.getTracks().forEach(track => track.stop());
        }
    }, 'image/jpeg', 0.95);
}

// إعادة التقاط الصورة
async function retakePhoto(isSelfie) {
    const video = document.getElementById(isSelfie ? 'selfieCamera' : 'idCamera');
    const preview = document.getElementById(isSelfie ? 'selfiePreview' : 'idPreview');
    const captureButton = document.getElementById(isSelfie ? 'captureSelfieButton' : 'captureIdButton');
    const retakeButton = document.getElementById(isSelfie ? 'retakeSelfieButton' : 'retakeIdButton');

    // إعادة تعيين المتغيرات
    if (isSelfie) {
        selfiePhotoBlob = null;
    } else {
        idPhotoBlob = null;
    }

    // إخفاء/إظهار العناصر المناسبة
    preview.style.display = 'none';
    video.style.display = 'block';
    captureButton.style.display = 'block';
    retakeButton.style.display = 'none';

    // إعادة تشغيل الكاميرا
    await initCamera(video, isSelfie ? 'user' : currentFacingMode);
}

// تبديل الكاميرا
async function switchCamera(isSelfie) {
    currentFacingMode = currentFacingMode === 'environment' ? 'user' : 'environment';
    const video = document.getElementById(isSelfie ? 'selfieCamera' : 'idCamera');
    await initCamera(video, currentFacingMode);
}

// إرسال النموذج
async function submitForm() {
    if (!validateStep3()) return;

    const loading = document.getElementById('loading');
    loading.style.display = 'block';

    try {
        const formData = new FormData();
        formData.append('full_name', document.getElementById('fullName').value);
        formData.append('id_number', document.getElementById('idNumber').value);
        formData.append('phone', document.getElementById('phone').value);
        formData.append('address', document.getElementById('address').value);
        formData.append('id_photo', idPhotoBlob, 'id_photo.jpg');
        formData.append('selfie_photo', selfiePhotoBlob, 'selfie_photo.jpg');
        formData.append('chat_id', telegram.initDataUnsafe?.user?.id);

        const response = await fetch('/submit', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (response.ok) {
            await Swal.fire({
                icon: 'success',
                title: 'تم بنجاح',
                text: 'تم استلام طلبك بنجاح. سيتم مراجعته وإبلاغك بالنتيجة.',
                confirmButtonText: 'حسناً'
            });
            telegram.close();
        } else {
            throw new Error(result.error || 'حدث خطأ أثناء إرسال الطلب');
        }
    } catch (error) {
        console.error('خطأ:', error);
        await Swal.fire({
            icon: 'error',
            title: 'خطأ',
            text: error.message || 'حدث خطأ أثناء إرسال الطلب',
            confirmButtonText: 'حسناً'
        });
    } finally {
        loading.style.display = 'none';
    }
}