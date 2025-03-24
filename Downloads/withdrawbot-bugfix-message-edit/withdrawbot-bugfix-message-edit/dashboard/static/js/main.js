// التعامل مع Modal الأكواد
let currentEditingCode = null;

function showCodeModal(isEdit = false, code = null) {
    const modal = document.getElementById('codeModal');
    const title = document.getElementById('codeModalTitle');
    const saveButton = document.getElementById('saveCodeButtonText');
    
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    
    if (isEdit && code) {
        title.textContent = 'تعديل الكود';
        saveButton.textContent = 'حفظ التغييرات';
        currentEditingCode = code;
        
        // تحميل بيانات الكود
        loadCodeDetails(code);
    } else {
        title.textContent = 'إضافة كود جديد';
        saveButton.textContent = 'إضافة';
        currentEditingCode = null;
        
        // تنظيف الحقول
        document.getElementById('codeInput').value = '';
        document.getElementById('codeDesc').value = '';
        document.getElementById('codeStatus').value = 'active';
        document.getElementById('codeMaxUses').value = '-1';
        document.getElementById('codeExpiry').value = '';
    }
}

function hideCodeModal() {
    const modal = document.getElementById('codeModal');
    const hasChanges = document.getElementById('codeInput').value || 
                      document.getElementById('codeDesc').value || 
                      document.getElementById('codeMaxUses').value !== '-1' ||
                      document.getElementById('codeExpiry').value;
    
    if (hasChanges) {
        if (!confirm('هل أنت متأكد من إلغاء العملية؟ سيتم فقدان البيانات المدخلة.')) {
            return;
        }
    }
    
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    currentEditingCode = null;
}

async function loadCodeDetails(code) {
    try {
        const response = await fetch(`/api/codes/${code}`);
        if (response.ok) {
            const data = await response.json();
            
            document.getElementById('codeInput').value = data.code;
            document.getElementById('codeDesc').value = data.description || '';
            document.getElementById('codeStatus').value = data.status;
            document.getElementById('codeMaxUses').value = data.max_uses;
            
            if (data.expiry_date) {
                const expiry = new Date(data.expiry_date);
                document.getElementById('codeExpiry').value = expiry.toISOString().slice(0, 16);
            } else {
                document.getElementById('codeExpiry').value = '';
            }
        } else {
            alert('حدث خطأ في تحميل بيانات الكود');
            hideCodeModal();
        }
    } catch (error) {
        console.error('Error:', error);
        alert('حدث خطأ في الاتصال');
        hideCodeModal();
    }
}

async function saveCode() {
    const codeInput = document.getElementById('codeInput');
    const codeMaxUses = document.getElementById('codeMaxUses');
    const codeExpiry = document.getElementById('codeExpiry');
    
    const codeData = {
        code: codeInput.value.trim(),
        description: document.getElementById('codeDesc').value.trim(),
        status: document.getElementById('codeStatus').value,
        max_uses: parseInt(codeMaxUses.value),
        expiry_date: codeExpiry.value || null
    };
    
    // التحقق من البيانات
    if (!codeData.code) {
        alert('الرجاء إدخال الكود');
        codeInput.focus();
        return;
    }
    
    if (codeData.max_uses !== -1 && (isNaN(codeData.max_uses) || codeData.max_uses < 1)) {
        alert('الرجاء إدخال قيمة صحيحة للحد الأقصى للاستخدام');
        codeMaxUses.focus();
        return;
    }
    
    // التحقق من تاريخ انتهاء الصلاحية
    if (codeExpiry.value) {
        const expiryDate = new Date(codeExpiry.value);
        const now = new Date();
        if (expiryDate <= now) {
            alert('تاريخ انتهاء الصلاحية يجب أن يكون في المستقبل');
            codeExpiry.focus();
            return;
        }
    }
    
    try {
        const url = currentEditingCode ? 
            `/api/codes/${currentEditingCode}` : 
            '/api/codes';
            
        const method = currentEditingCode ? 'PUT' : 'POST';
        
        const response = await fetch(url, {
            method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(codeData)
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            alert(currentEditingCode ? 'تم تحديث الكود بنجاح' : 'تم إضافة الكود بنجاح');
            hideCodeModal();
            window.location.reload();
        } else {
            const errorMessage = result.error || 'حدث خطأ أثناء حفظ الكود';
            alert(errorMessage);
            
            // تحديد الحقل الذي يحتاج إلى تركيز بناءً على نوع الخطأ
            if (errorMessage.includes('Code already exists')) {
                codeInput.focus();
            } else if (errorMessage.includes('max uses')) {
                codeMaxUses.focus();
            } else if (errorMessage.includes('expiry')) {
                codeExpiry.focus();
            }
        }
    } catch (error) {
        console.error('Error:', error);
        alert('حدث خطأ في الاتصال بالخادم');
    }
}

async function activateCode(code) {
    await updateCodeStatus(code, 'active');
}

async function deactivateCode(code) {
    await updateCodeStatus(code, 'inactive');
}

async function updateCodeStatus(code, status) {
    if (!confirm(`هل أنت متأكد من ${status === 'active' ? 'تفعيل' : 'إيقاف'} هذا الكود؟`)) return;
    
    try {
        const response = await fetch(`/api/codes/${code}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ status })
        });
        
        if (response.ok) {
            window.location.reload();
        } else {
            alert('حدث خطأ أثناء تحديث حالة الكود');
        }
    } catch (error) {
        console.error('Error:', error);
        alert('حدث خطأ في الاتصال');
    }
}

async function deleteCode(code) {
    if (!confirm('هل أنت متأكد من حذف هذا الكود؟\nسيتم إلغاء ارتباط جميع المستخدمين بهذا الكود.')) return;
    
    try {
        const response = await fetch(`/api/codes/${code}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            window.location.reload();
        } else {
            alert('حدث خطأ أثناء حذف الكود');
        }
    } catch (error) {
        console.error('Error:', error);
        alert('حدث خطأ في الاتصال');
    }
}

// حفظ الإعدادات
async function saveSettings() {
    // التحقق من وجود تغييرات
    const originalSettings = window.originalSettings || {};
    const currentSettings = {
        fixed_fee_threshold: parseFloat(document.getElementById('fixedFeeThreshold').value),
        fixed_fee_amount: parseFloat(document.getElementById('fixedFeeAmount').value),
        percentage_fee: parseFloat(document.getElementById('percentageFee').value),
        min_withdrawal: parseFloat(document.getElementById('minWithdrawal').value),
        max_withdrawal: parseFloat(document.getElementById('maxWithdrawal').value)
    };

    // التحقق من وجود تغييرات
    let hasChanges = false;
    for (const key in currentSettings) {
        if (currentSettings[key] !== originalSettings[key]) {
            hasChanges = true;
            break;
        }
    }

    if (!hasChanges) {
        alert('لم يتم إجراء أي تغييرات');
        return;
    }

    // تأكيد حفظ التغييرات
    if (!confirm('هل أنت متأكد من حفظ التغييرات؟')) {
        return;
    }

    const settings = currentSettings;

    // التحقق من صحة القيم
    if (isNaN(settings.fixed_fee_threshold) || settings.fixed_fee_threshold <= 0) {
        alert('الرجاء إدخال قيمة صحيحة للحد الفاصل للعمولة الثابتة');
        return;
    }
    if (isNaN(settings.fixed_fee_amount) || settings.fixed_fee_amount < 0) {
        alert('الرجاء إدخال قيمة صحيحة للعمولة الثابتة');
        return;
    }
    if (isNaN(settings.percentage_fee) || settings.percentage_fee < 0 || settings.percentage_fee > 100) {
        alert('الرجاء إدخال نسبة عمولة صحيحة (بين 0 و 100)');
        return;
    }
    if (isNaN(settings.min_withdrawal) || settings.min_withdrawal <= 0) {
        alert('الرجاء إدخال قيمة صحيحة للحد الأدنى للسحب');
        return;
    }
    if (isNaN(settings.max_withdrawal) || settings.max_withdrawal <= settings.min_withdrawal) {
        alert('الرجاء إدخال قيمة صحيحة للحد الأعلى للسحب (يجب أن تكون أكبر من الحد الأدنى)');
        return;
    }

    try {
        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(settings)
        });

        if (response.ok) {
            alert('تم حفظ الإعدادات بنجاح');
        } else {
            alert('حدث خطأ أثناء حفظ الإعدادات');
        }
    } catch (error) {
        console.error('Error:', error);
        alert('حدث خطأ في الاتصال');
    }
}

// تحميل الإعدادات عند فتح الصفحة
// التعامل مع Modal أسعار الصرف
function showAddRateModal() {
    document.getElementById('rateModal').classList.remove('hidden');
    document.getElementById('rateModal').classList.add('flex');
    document.getElementById('rateModalTitle').textContent = 'إضافة عملة جديدة';
    // تنظيف الحقول
    document.getElementById('currencyCode').value = '';
    document.getElementById('exchangeRate').value = '';
    document.getElementById('currencyCode').removeAttribute('readonly');
}

function showEditRateModal(currency, rate) {
    document.getElementById('rateModal').classList.remove('hidden');
    document.getElementById('rateModal').classList.add('flex');
    document.getElementById('rateModalTitle').textContent = 'تعديل سعر الصرف';
    // تعبئة البيانات
    document.getElementById('currencyCode').value = currency;
    document.getElementById('exchangeRate').value = rate;
    document.getElementById('currencyCode').setAttribute('readonly', true);
}

function hideRateModal() {
    if (document.getElementById('exchangeRate').value) {
        if (!confirm('هل أنت متأكد من إلغاء العملية؟ سيتم فقدان البيانات المدخلة.')) {
            return;
        }
    }
    document.getElementById('rateModal').classList.add('hidden');
    document.getElementById('rateModal').classList.remove('flex');
}

// حفظ سعر الصرف
async function saveExchangeRate() {
    const currency = document.getElementById('currencyCode').value.trim().toUpperCase();
    const rate = parseFloat(document.getElementById('exchangeRate').value);

    // التحقق من إدخال جميع البيانات
    if (!currency) {
        alert('الرجاء إدخال رمز العملة');
        document.getElementById('currencyCode').focus();
        return;
    }
    if (isNaN(rate) || rate <= 0) {
        alert('الرجاء إدخال سعر صرف صحيح');
        document.getElementById('exchangeRate').focus();
        return;
    }

    try {
        const response = await fetch(`/api/exchange-rates/${currency}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ rate })
        });

        if (response.ok) {
            alert('تم حفظ سعر الصرف بنجاح');
            hideRateModal();
            loadExchangeRates();
        } else {
            alert('حدث خطأ أثناء حفظ سعر الصرف');
        }
    } catch (error) {
        console.error('Error:', error);
        alert('حدث خطأ في الاتصال');
    }
}

// حذف سعر الصرف
async function deleteExchangeRate(currency) {
    if (!confirm('هل أنت متأكد من حذف سعر صرف هذه العملة؟')) return;

    try {
        const response = await fetch(`/api/exchange-rates/${currency}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            loadExchangeRates();
        } else {
            alert('حدث خطأ أثناء حذف سعر الصرف');
        }
    } catch (error) {
        console.error('Error:', error);
        alert('حدث خطأ في الاتصال');
    }
}

// تحميل أسعار الصرف
async function loadExchangeRates() {
    try {
        const response = await fetch('/api/exchange-rates');
        if (response.ok) {
            const rates = await response.json();
            const tbody = document.getElementById('exchangeRatesList');
            tbody.innerHTML = '';
            
            for (const [currency, data] of Object.entries(rates)) {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td class="px-6 py-4">${currency}</td>
                    <td class="px-6 py-4">${data.rate}</td>
                    <td class="px-6 py-4">${new Date(data.updated_at).toLocaleString('ar-SA')}</td>
                    <td class="px-6 py-4">
                        <button onclick="showEditRateModal('${currency}', ${data.rate})" class="text-yellow-500 px-2">تعديل</button>
                        <button onclick="deleteExchangeRate('${currency}')" class="text-red-500 px-2">حذف</button>
                    </td>
                `;
                tbody.appendChild(row);
            }
        }
    } catch (error) {
        console.error('Error loading exchange rates:', error);
        alert('حدث خطأ في تحميل أسعار الصرف');
    }
}

window.onload = async function() {
    // تحميل أسعار الصرف
    await loadExchangeRates();

    // تحميل الإعدادات
    try {
        const response = await fetch('/api/settings');
        if (response.ok) {
            const settings = await response.json();
            // حفظ الإعدادات الأصلية
            window.originalSettings = {
                fixed_fee_threshold: settings.fixed_fee_threshold,
                fixed_fee_amount: settings.fixed_fee_amount,
                percentage_fee: settings.percentage_fee,
                min_withdrawal: settings.min_withdrawal,
                max_withdrawal: settings.max_withdrawal
            };
            // عرض الإعدادات في النموذج
            document.getElementById('fixedFeeThreshold').value = settings.fixed_fee_threshold;
            document.getElementById('fixedFeeAmount').value = settings.fixed_fee_amount;
            document.getElementById('percentageFee').value = settings.percentage_fee;
            document.getElementById('minWithdrawal').value = settings.min_withdrawal;
            document.getElementById('maxWithdrawal').value = settings.max_withdrawal;
        }
    } catch (error) {
        console.error('Error loading settings:', error);
        alert('حدث خطأ في تحميل الإعدادات');
    }

    // إضافة مستمع لأحداث الخروج من الصفحة
    window.addEventListener('beforeunload', function(e) {
        // التحقق من وجود تغييرات غير محفوظة
        const currentSettings = {
            fixed_fee_threshold: parseFloat(document.getElementById('fixedFeeThreshold').value),
            fixed_fee_amount: parseFloat(document.getElementById('fixedFeeAmount').value),
            percentage_fee: parseFloat(document.getElementById('percentageFee').value),
            min_withdrawal: parseFloat(document.getElementById('minWithdrawal').value),
            max_withdrawal: parseFloat(document.getElementById('maxWithdrawal').value)
        };

        let hasChanges = false;
        for (const key in currentSettings) {
            if (currentSettings[key] !== window.originalSettings[key]) {
                hasChanges = true;
                break;
            }
        }

        if (hasChanges) {
            e.preventDefault();
            e.returnValue = 'لديك تغييرات غير محفوظة. هل أنت متأكد من مغادرة الصفحة؟';
            return e.returnValue;
        }
    });
};
