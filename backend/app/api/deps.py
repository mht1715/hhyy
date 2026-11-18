from fastapi import Depends, HTTPException, status

from app.api.auth import get_current_user
from app.models.user import User, UserRole


def require_roles(allowed_roles: list[UserRole]):
    """
    通用角色校验工厂。
    用法：Depends(require_roles([UserRole.ADMIN, UserRole.DOCTOR]))
    """

    def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                # 不要在这里写死「管理员和医生」：AnyUser 也走这个工厂，
                # 客服账号会被误导成「系统只给管理员和医生用」
                detail="当前身份无权访问该接口"
            )
        return current_user

    return checker


# 预设常用的权限组，方便直接调用
AdminOnly = Depends(require_roles([UserRole.ADMIN]))
AdminOrDoctor = Depends(require_roles([UserRole.ADMIN, UserRole.DOCTOR]))
# 任何已登录角色：客服也是登录用户（M1 加角色时漏了，导致客服一登录就被购物车 403 顶掉）
AnyUser = Depends(
    require_roles([UserRole.ADMIN, UserRole.DOCTOR, UserRole.PATIENT, UserRole.SUPPORT])
)
