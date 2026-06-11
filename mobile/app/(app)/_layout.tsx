import { Ionicons } from '@expo/vector-icons';
import { Redirect, Tabs } from 'expo-router';

import { useAuth } from '../../src/auth/AuthContext';
import { useUnread } from '../../src/contexts/UnreadContext';
import { colors as C } from '../../src/theme';

type IoniconsName = React.ComponentProps<typeof Ionicons>['name'];

function TabIcon({ name, focused }: { name: IoniconsName; focused: boolean }) {
  return (
    <Ionicons
      name={focused ? name : (`${name}-outline` as IoniconsName)}
      size={24}
      color={focused ? C.accentHover : C.textDisabled}
    />
  );
}

export default function AppLayout() {
  const { user, loading } = useAuth();
  const { totalUnread }   = useUnread();

  if (loading) return null;
  if (!user)   return <Redirect href="/(auth)/login" />;

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarStyle: {
          backgroundColor: C.bgNav,
          borderTopColor: C.border,
          borderTopWidth: 1,
        },
        tabBarActiveTintColor: C.accentHover,
        tabBarInactiveTintColor: C.textDisabled,
        tabBarLabelStyle: { fontSize: 11, fontWeight: '500' },
      }}
    >
      <Tabs.Screen
        name="discover"
        options={{
          title: 'Discover',
          tabBarIcon: ({ focused }) => <TabIcon name="compass" focused={focused} />,
        }}
      />
      <Tabs.Screen
        name="matches"
        options={{
          title: 'Matches',
          tabBarIcon: ({ focused }) => <TabIcon name="heart" focused={focused} />,
          tabBarBadge: totalUnread > 0 ? (totalUnread > 99 ? '99+' : totalUnread) : undefined,
          tabBarBadgeStyle: { backgroundColor: C.gold, color: '#0D0B1A', fontSize: 10, minWidth: 16, height: 16 },
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: 'Profile',
          tabBarIcon: ({ focused }) => <TabIcon name="person" focused={focused} />,
        }}
      />
      {/* Chat is a pushed screen — hide from tab bar, suppress tab bar when active */}
      <Tabs.Screen
        name="chat/[matchId]"
        options={{
          href: null,
          tabBarStyle: { display: 'none' },
        }}
      />
    </Tabs>
  );
}
