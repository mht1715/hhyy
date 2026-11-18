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
                detail="权限不足，仅限管理员和医生操作"
            )
        return current_user

    return checker


# 预设常用的权限组，方便直接调用
AdminOnly = Depends(require_roles([UserRole.ADMIN]))
AdminOrDoctor = Depends(require_roles([UserRole.ADMIN, UserRole.DOCTOR]))
AnyUser = Depends(require_roles([UserRole.ADMIN, UserRole.DOCTOR, UserRole.PATIENT]))
