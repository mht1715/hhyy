<script setup>
import {useRouter} from 'vue-router'

const router = useRouter()
</script>
<template>
  <div style="padding: 100px; text-align: center;">
    <h2>订单结算页</h2>
    <p style="margin-top: 20px;">此页面开发中，后续将对接真实支付。</p>
    <van-button type="danger" style="margin-top: 20px;" @click="router.back()">返回</van-button>
  </div>
</template>