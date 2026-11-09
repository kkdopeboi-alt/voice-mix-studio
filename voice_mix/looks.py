"""Shared picture-only grades, applied before text overlays."""
LOOKS = {
    'none': ('原色', (1,0,1,1,1)),
    'clear': ('清透明亮', (1.10,.012,1.12,1,1)),
    'warm': ('暖阳', (1.04,.008,1.06,1.04,.97)),
    'cool': ('清冷', (1.06,0,.94,.97,1.04)),
    'soft': ('柔雾', (.94,.025,.90,1.01,1)),
    'mono': ('经典黑白', (1.10,0,0,1,1)),
    'cream': ('奶油肤色', (.96,.025,.88,1.025,.98)),
    'film': ('胶片故事', (1.08,-.008,.82,1.035,.97)),
    'food': ('食物鲜活', (1.08,.018,1.18,1.025,.98)),
    'product': ('商品质感', (1.12,.008,1.03,1,1)),
    'forest': ('森系', (1.03,-.006,.85,.98,1.015)),
    'sunset': ('落日金色', (1.05,.01,1.08,1.07,.94)),
    'night': ('城市夜景', (1.13,-.025,.90,.98,1.045)),
    'vintage': ('复古褪色', (.91,.02,.72,1.045,.96)),
    'airy': ('日系空气', (.92,.035,.83,1.01,1.02)),
    'dramatic': ('深邃电影', (1.18,-.02,.78,1.01,1.025)),
}


def grade(name, strength=1):
    if name == 'none' or not strength:
        return 'null'
    contrast, brightness, saturation, red, blue = LOOKS[name][1]
    return (f'eq=contrast={1+(contrast-1)*strength}:brightness={brightness*strength}:'
            f'saturation={1+(saturation-1)*strength}:gamma_r={1+(red-1)*strength}:'
            f'gamma_b={1+(blue-1)*strength}')
