'use strict';
// No offline caching of private data or API responses.
self.addEventListener('push',event=>{let data={title:'Family OS',body:'Eine neue Mitteilung liegt bereit.',tag:'fos'};try{data={...data,...event.data.json()};}catch(_){}event.waitUntil(self.registration.showNotification(data.title,{body:data.body,tag:data.tag,icon:'/static/favicon.svg',data:{url:'/'}}));});
self.addEventListener('notificationclick',event=>{event.notification.close();event.waitUntil((async()=>{const list=await self.clients.matchAll({type:'window',includeUncontrolled:true});for(const client of list){if(new URL(client.url).origin===self.location.origin){await client.focus();return;}}await self.clients.openWindow('/');})());});
