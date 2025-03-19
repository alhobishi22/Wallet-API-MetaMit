<?php
// تكوين الاتصال بقاعدة البيانات
$dbconn = pg_connect("host=dpg-csserj9u0jms73ea9gmg-a.singapore-postgres.render.com port=5432 dbname=meta_bit_database user=alhubaishi password=jAtNbIdExraRUo1ZosQ1f0EEGz3fMZWt");

if (!$dbconn) {
    die("خطأ في الاتصال بقاعدة البيانات");
}

// استعلام لجلب إحصائيات العمليات
$query_stats = "
    SELECT 
        COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_count,
        COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending_count,
        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_count,
        COUNT(*) as total_count,
        SUM(CASE WHEN status = 'pending' THEN crypto_amount ELSE 0 END) as pending_amount,
        SUM(CASE WHEN status = 'completed' THEN crypto_amount ELSE 0 END) as completed_amount
    FROM withdrawal_requests";

$result = pg_query($dbconn, $query_stats);
$stats = pg_fetch_assoc($result);

// استعلام لجلب آخر العمليات
$query_recent = "
    SELECT 
        withdrawal_id as transaction_id,
        user_id,
        crypto_currency as currency,
        crypto_amount as amount,
        status,
        created_at as date
    FROM withdrawal_requests 
    ORDER BY created_at DESC 
    LIMIT 10";

$recent_transactions = pg_query($dbconn, $query_recent);
?>

<!DOCTYPE html>
<html dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>لوحة المعلومات</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    </style>
</head>
<body>
    <div class="container mt-4">
        <h2 class="mb-4">لوحة المعلومات</h2>
        
        <!-- بطاقات الإحصائيات -->
        <div class="row mb-4">
            <div class="col-md-3">
                <div class="card bg-primary text-white">
                    <div class="card-body">
                        <h5 class="card-title">إجمالي العمليات</h5>
                        <h2><?php echo $stats['total_count']; ?></h2>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card bg-success text-white">
                    <div class="card-body">
                        <h5 class="card-title">العمليات المكتملة</h5>
                        <h2><?php echo $stats['completed_count']; ?></h2>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card bg-warning text-dark">
                    <div class="card-body">
                        <h5 class="card-title">العمليات المعلقة</h5>
                        <h2><?php echo $stats['pending_count']; ?></h2>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card bg-danger text-white">
                    <div class="card-body">
                        <h5 class="card-title">العمليات الفاشلة</h5>
                        <h2><?php echo $stats['failed_count']; ?></h2>
                    </div>
                </div>
            </div>
        </div>

        <!-- المبالغ الإجمالية -->
        <div class="row mb-4">
            <div class="col-md-6">
                <div class="card">
                    <div class="card-body">
                        <h5 class="card-title">إجمالي المبالغ المكتملة (USD)</h5>
                        <h3>$<?php echo number_format($stats['completed_amount'], 2); ?></h3>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card">
                    <div class="card-body">
                        <h5 class="card-title">إجمالي المبالغ المعلقة (USD)</h5>
                        <h3>$<?php echo number_format($stats['pending_amount'], 2); ?></h3>
                    </div>
                </div>
            </div>
        </div>

        <!-- جدول آخر العمليات -->
        <div class="card">
            <div class="card-body">
                <h5 class="card-title">آخر العمليات</h5>
                <table class="table">
                    <thead>
                        <tr>
                            <th>معرف العملية</th>
                            <th>المستخدم</th>
                            <th>العملة</th>
                            <th>المبلغ</th>
                            <th>الحالة</th>
                            <th>التاريخ</th>
                        </tr>
                    </thead>
                    <tbody>
                        <?php while ($row = pg_fetch_assoc($recent_transactions)) { ?>
                            <tr>
                                <td><?php echo $row['transaction_id']; ?></td>
                                <td><?php echo $row['user_id']; ?></td>
                                <td><?php echo $row['currency']; ?></td>
                                <td><?php echo $row['amount']; ?></td>
                                <td>
                                    <span class="badge bg-<?php 
                                        echo $row['status'] == 'completed' ? 'success' : 
                                            ($row['status'] == 'pending' ? 'warning' : 'danger'); 
                                    ?>">
                                        <?php echo $row['status']; ?>
                                    </span>
                                </td>
                                <td><?php echo date('Y-m-d H:i', strtotime($row['date'])); ?></td>
                            </tr>
                        <?php } ?>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>